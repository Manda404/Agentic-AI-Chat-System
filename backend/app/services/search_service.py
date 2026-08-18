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

`pymongo` est un driver SYNCHRONE : `aggregate()`/`insert_many()` bloquent le
thread appelant le temps de l'aller-retour réseau. Comme ce service est
utilisé depuis des méthodes `async def` (agents LangGraph, routes FastAPI),
chaque appel bloquant est délégué à `asyncio.to_thread` pour ne jamais geler
l'event loop pendant une requête Mongo.
"""

import asyncio
from typing import Any, Dict, List

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

            self._client = mongo_client_class(settings.mongodb_uri, serverSelectionTimeoutMS=5000)
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
        """Insère une liste de documents (déjà enrichis d'un champ `embedding` si besoin)."""
        if self._collection is None:
            raise RuntimeError("MongoDB Atlas is not available.")
        logger.bind(collection=self.index_name, document_count=len(documents)).info(
            "Bulk index started."
        )
        if not documents:
            return 0
        await asyncio.to_thread(self._collection.insert_many, documents)
        logger.bind(collection=self.index_name, document_count=len(documents)).info(
            "Bulk index completed."
        )
        return len(documents)

    async def search(self, query: str) -> List[SearchResult]:
        """Recherche full-text (Atlas Search, compound text) sur title/snippet/category, top 5 résultats."""
        if self._collection is None:
            raise RuntimeError("MongoDB Atlas is not available. Please ingest data and check MONGODB_URI.")
        logger.bind(collection=self.index_name, query_preview=query[:120]).info(
            "MongoDB Atlas Search query started."
        )
        try:
            pipeline = [
                {
                    "$search": {
                        "index": settings.mongodb_search_index,
                        "compound": {
                            "should": [
                                {"text": {"query": query, "path": "title", "score": {"boost": {"value": 2}}}},
                                {"text": {"query": query, "path": "snippet"}},
                                {"text": {"query": query, "path": "category"}},
                            ]
                        },
                    }
                },
                {"$limit": 5},
                {"$addFields": {"score": {"$meta": "searchScore"}}},
            ]
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
                )
                for hit in hits
            ]
        except Exception as exc:
            logger.bind(collection=self.index_name, query_preview=query[:120]).exception(
                "MongoDB Atlas Search query failed."
            )
            raise RuntimeError(f"MongoDB Atlas Search query failed: {exc}") from exc

    async def list_indexed_documents(self, limit: int = 200) -> List[Dict[str, Any]]:
        """Retourne un inventaire borné des métadonnées documentaires indexées."""
        if self._collection is None:
            raise RuntimeError("MongoDB Atlas is not available.")
        safe_limit = max(1, min(limit, 1000))

        def fetch_documents() -> List[Dict[str, Any]]:
            cursor = self._collection.find(
                {},
                {
                    "_id": 0,
                    "title": 1,
                    "file_name": 1,
                    "page_number": 1,
                    "source": 1,
                    "category": 1,
                },
            ).limit(safe_limit)
            return list(cursor)

        return await asyncio.to_thread(fetch_documents)

    async def clear_documents(self) -> int:
        """Supprime tous les documents de la collection sans supprimer ses index Atlas."""
        if self._collection is None:
            raise RuntimeError("MongoDB Atlas is not available.")
        result = await asyncio.to_thread(self._collection.delete_many, {})
        deleted_count = int(result.deleted_count)
        logger.bind(collection=self.index_name, deleted_count=deleted_count).warning(
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
