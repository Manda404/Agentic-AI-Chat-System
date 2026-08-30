"""
Service de recherche documentaire basé sur MongoDB Atlas (Atlas Search).

Encapsule la connexion pymongo (tolérante aux pannes — si MongoDB Atlas est
injoignable au démarrage, le service reste utilisable mais `available` devient
`False` et toute recherche lève une erreur explicite) et la recherche full-text
via l'index Atlas Search configuré côté cluster (`settings.mongodb_search_index`).

L'indexation (`bulk_index_documents`) attend des documents déjà enrichis d'un
champ `embedding` par l'appelant (voir `ingest_router.py`), afin que la même
collection serve aussi de source à `MongoVectorStore` pour la recherche
vectorielle (Atlas Vector Search).

Les méthodes de lecture acceptent `owner_id` : en `DOCUMENT_SCOPE_MODE=owner`,
les requêtes ne voient que les documents du propriétaire et les documents
marqués `shared`.

`pymongo` est un driver SYNCHRONE : `aggregate()`/`insert_many()` bloquent le
thread appelant le temps de l'aller-retour réseau. Comme ce service est
utilisé depuis des méthodes `async def` (agents LangGraph, routes FastAPI),
chaque appel bloquant est délégué à `asyncio.to_thread` pour ne jamais geler
l'event loop pendant une requête Mongo.
"""

import asyncio
import hashlib
from typing import Any, Dict, List

import certifi

from app.config.settings import settings
from app.logger import logger
from app.models.chat_models import SearchResult


class SearchService:
    """Point d'accès unique à MongoDB Atlas pour indexer et rechercher des documents (full-text)."""

    def __init__(self) -> None:
        """Tente une connexion à MongoDB Atlas ; échoue silencieusement (mode dégradé) si indisponible."""
        self.index_name = settings.mongodb_collection
        self._client = None
        self._collection = None

        try:
            import importlib

            pymongo_module = importlib.import_module("pymongo")
            mongo_client_class = getattr(pymongo_module, "MongoClient")

            self._client = mongo_client_class(
                settings.mongodb_uri,
                serverSelectionTimeoutMS=5000,
                tls=True,
                tlsCAFile=certifi.where(),
            )
            self._client.admin.command("ping")
            self._collection = self._client[settings.mongodb_db_name][settings.mongodb_collection]

            logger.bind(
                db_name=settings.mongodb_db_name,
                collection=self.index_name,
            ).info("MongoDB Atlas client initialized.")

        except Exception as exc:
            logger.bind(collection=self.index_name, reason=str(exc)).warning(
                "MongoDB Atlas client unavailable during startup."
            )
            self._client = None
            self._collection = None

    @property
    def collection(self):
        """Expose la collection pymongo (réutilisée par `MongoVectorStore`, évite une 2e connexion)."""
        return self._collection

    async def bulk_index_documents(self, documents: List[Dict[str, Any]]) -> int:
        """Upsert une liste de documents déjà enrichis d'un `_id` stable si possible."""
        if self._collection is None:
            raise RuntimeError("MongoDB Atlas is not available.")
        logger.bind(collection=self.index_name, document_count=len(documents)).info(
            "Bulk index started."
        )
        if not documents:
            return 0
        normalized_by_id = {
            document["_id"]: document
            for document in (self._with_stable_id(document) for document in documents)
        }
        normalized_documents = list(normalized_by_id.values())
        try:
            import importlib

            pymongo_module = importlib.import_module("pymongo")
            replace_one = getattr(pymongo_module, "ReplaceOne")
            operations = [
                replace_one({"_id": document["_id"]}, document, upsert=True)
                for document in normalized_documents
            ]
            result = await asyncio.to_thread(self._collection.bulk_write, operations, ordered=False)
            indexed_count = int(result.upserted_count + result.modified_count + result.matched_count)
        except Exception:
            logger.exception("Bulk upsert failed; falling back to insert_many.")
            await asyncio.to_thread(self._collection.insert_many, normalized_documents)
            indexed_count = len(normalized_documents)
        logger.bind(collection=self.index_name, document_count=len(normalized_documents)).info(
            "Bulk index completed."
        )
        return indexed_count

    async def search(self, query: str, owner_id: str | None = None) -> List[SearchResult]:
        """Recherche full-text (Atlas Search, compound text) sur title/snippet/category, top 5 résultats."""
        if self._collection is None:
            raise RuntimeError("MongoDB Atlas is not available. Please ingest data and check MONGODB_URI.")
        logger.bind(collection=self.index_name, query_preview=query[:120]).info(
            "MongoDB Atlas Search query started."
        )
        try:
            pipeline: list[dict[str, Any]] = [
                {
                    "$search": {
                        "index": settings.mongodb_search_index,
                        "compound": {
                            "should": [
                                {"text": {"query": query, "path": "title", "score": {"boost": {"value": 2}}}},
                                {"text": {"query": query, "path": "snippet"}},
                                {"text": {"query": query, "path": "category"}},
                            ],
                            "minimumShouldMatch": 1,
                        },
                    }
                },
            ]
            access_filter = self._search_access_filter(owner_id)
            if access_filter:
                pipeline.append({"$match": access_filter})
            pipeline.extend(
                [
                    {"$limit": 5},
                    {"$addFields": {"score": {"$meta": "searchScore"}}},
                ]
            )
            hits = await asyncio.to_thread(lambda: list(self._collection.aggregate(pipeline)))
            logger.bind(collection=self.index_name, hits_count=len(hits)).info(
                "MongoDB Atlas Search query completed."
            )
            return [
                SearchResult(
                    title=hit.get("title", "Untitled"),
                    snippet=hit.get("snippet", ""),
                    score=float(hit.get("score", 0.0)),
                    source=hit.get("source", "mongodb"),
                    page_number=hit.get("page_number"),
                    file_name=hit.get("file_name"),
                    document_id=str(hit.get("document_id") or hit.get("_id") or "") or None,
                    embedding=hit.get("embedding"),
                )
                for hit in hits
            ]
        except Exception as exc:
            logger.bind(collection=self.index_name, query_preview=query[:120]).exception(
                "MongoDB Atlas Search query failed."
            )
            raise RuntimeError(f"MongoDB Atlas Search query failed: {exc}") from exc

    async def list_indexed_documents(
        self,
        limit: int = 200,
        owner_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Retourne un inventaire borné des métadonnées documentaires indexées."""
        if self._collection is None:
            raise RuntimeError("MongoDB Atlas is not available.")
        safe_limit = max(1, min(limit, 1000))
        access_filter = self._search_access_filter(owner_id)

        def fetch_documents() -> List[Dict[str, Any]]:
            cursor = self._collection.find(
                access_filter,
                {
                    "_id": 0,
                    "title": 1,
                    "file_name": 1,
                    "page_number": 1,
                    "source": 1,
                    "category": 1,
                    "document_id": 1,
                    "owner_id": 1,
                    "visibility": 1,
                },
            ).limit(safe_limit)
            return list(cursor)

        return await asyncio.to_thread(fetch_documents)

    async def clear_documents(self, owner_id: str | None = None) -> int:
        """Supprime tous les documents de la collection sans supprimer ses index Atlas."""
        if self._collection is None:
            raise RuntimeError("MongoDB Atlas is not available.")
        filter_query = self._owner_filter(owner_id)
        result = await asyncio.to_thread(self._collection.delete_many, filter_query)
        deleted_count = int(result.deleted_count)
        logger.bind(
            collection=self.index_name,
            owner_scoped=bool(filter_query),
            deleted_count=deleted_count,
        ).warning(
            "MongoDB document collection reset completed."
        )
        return deleted_count

    @property
    def available(self) -> bool:
        """True si la connexion MongoDB Atlas a réussi au démarrage (utilisé par `/health`)."""
        return self._collection is not None

    def close(self) -> None:
        """Ferme le client MongoDB possédé par ce service."""
        if self._client is not None:
            self._client.close()

    def _with_stable_id(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """Retourne une copie du document avec `_id` et `document_id` déterministes."""
        normalized = dict(document)
        document_id = str(normalized.get("document_id") or normalized.get("_id") or "").strip()
        if not document_id:
            identity_owner = (
                str(normalized.get("owner_id", "") or "").strip().lower()
                if normalized.get("visibility") == "private"
                else ""
            )
            identity = "|".join(
                [identity_owner]
                + [
                    str(normalized.get(key, "") or "").strip()
                    for key in ("source", "file_name", "page_number", "title", "snippet")
                ]
            )
            document_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()
        normalized["document_id"] = document_id
        normalized["_id"] = document_id
        return normalized

    def _search_access_filter(self, owner_id: str | None) -> Dict[str, Any]:
        """Filtre de visibilité appliqué aux recherches et inventaires."""
        if settings.document_scope_mode != "owner":
            return {}
        if owner_id:
            return {"$or": [{"owner_id": owner_id}, {"visibility": "shared"}]}
        return {"visibility": "shared"}

    def _owner_filter(self, owner_id: str | None) -> Dict[str, Any]:
        """Filtre de suppression : en mode owner, un non-admin ne supprime que ses documents."""
        if settings.document_scope_mode == "owner" and owner_id:
            return {"owner_id": owner_id}
        return {}
