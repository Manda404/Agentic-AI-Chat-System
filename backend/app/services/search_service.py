"""MongoDB Atlas document storage and text retrieval. If the startup connection fails, available is false and searches raise an explicit error. Ingestion supplies prepared embeddings so the same collection supports vector retrieval. Owner-scoped reads include the user's documents and shared documents. Blocking PyMongo runtime operations use asyncio.to_thread to avoid blocking asynchronous routes and agents."""

import asyncio
from typing import Any, Dict, List

import certifi

from app.config.settings import settings
from app.data_ingest.document_processing import with_document_id
from app.logger import logger
from app.models.chat_models import SearchResult


class SearchService:
    """Shared MongoDB Atlas access for indexing and text retrieval."""

    def __init__(self) -> None:
        """Attempt an Atlas connection; retain an explicit degraded state if unavailable."""
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
        """Expose the connected PyMongo collection for reuse by MongoVectorStore."""
        return self._collection

    async def bulk_index_documents(self, documents: List[Dict[str, Any]]) -> int:
        """Upsert prepared documents, assigning stable identities where possible."""
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
        from pymongo import UpdateOne

        # $set preserves an existing vector when identical reingestion fails at the provider.
        operations = [
            UpdateOne({"_id": document["_id"]},
                      {"$set": {key: value for key, value in document.items() if key != "_id"}},
                      upsert=True)
            for document in normalized_documents
        ]
        result = await asyncio.to_thread(self._collection.bulk_write, operations, ordered=False)
        # modified_count is already included in matched_count.
        indexed_count = int(result.upserted_count + result.matched_count)
        logger.bind(collection=self.index_name, document_count=len(normalized_documents)).info(
            "Bulk index completed."
        )
        return indexed_count

    async def search(self, query: str, owner_id: str | None = None) -> List[SearchResult]:
        """Run Atlas compound text search over title, snippet and category, returning up to five hits."""
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

    async def get_passage(self, passage_id: str, owner_id: str | None = None) -> SearchResult | None:
        """Read a known fragment with the same access filter used by search."""
        if self._collection is None:
            raise RuntimeError("MongoDB Atlas is not available.")
        from bson import ObjectId

        ids: list[Any] = [passage_id]
        if ObjectId.is_valid(passage_id):
            ids.append(ObjectId(passage_id))
        identity = {"$or": [{"document_id": passage_id}, {"_id": {"$in": ids}}]}
        query = {"$and": [identity, self._search_access_filter(owner_id)]}
        hit = await asyncio.to_thread(self._collection.find_one, query, {"embedding": 0})
        if hit is None:
            return None
        return SearchResult(
            document_id=str(hit.get("document_id") or hit["_id"]),
            title=hit.get("title", "Untitled"), snippet=hit.get("snippet", ""),
            source=hit.get("source", "mongodb"), score=0.0,
            file_name=hit.get("file_name"), page_number=hit.get("page_number"),
        )

    async def list_indexed_documents(
        self,
        limit: int = 200,
        owner_id: str | None = None,
    ) -> List[Dict[str, Any]]:
        """Return a bounded inventory of indexed document metadata."""
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
        """Remove matching documents while preserving Atlas indexes."""
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
        """Whether the startup Atlas connection succeeded, as reported by /health."""
        return self._collection is not None

    def close(self) -> None:
        """Close the MongoDB client owned by this service."""
        if self._client is not None:
            self._client.close()

    def _with_stable_id(self, document: Dict[str, Any]) -> Dict[str, Any]:
        """Return a copy with deterministic _id and document_id fields."""
        return with_document_id(document)

    def _search_access_filter(self, owner_id: str | None) -> Dict[str, Any]:
        """Build the visibility filter applied to retrieval and inventory reads."""
        if settings.document_scope_mode != "owner":
            return {}
        if owner_id:
            return {"$or": [{"owner_id": owner_id}, {"visibility": "shared"}]}
        return {"visibility": "shared"}

    def _owner_filter(self, owner_id: str | None) -> Dict[str, Any]:
        """Build the deletion filter: non-admin users in owner mode can delete only their documents."""
        if settings.document_scope_mode == "owner" and owner_id:
            return {"owner_id": owner_id}
        return {}
