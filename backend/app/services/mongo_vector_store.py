"""Atlas Vector Search implementation of VectorStorePort. Reuse SearchService's MongoDB collection and an embedding service for the query. Run synchronous PyMongo aggregation through asyncio.to_thread so network I/O does not block the event loop."""

import asyncio

from app.config.settings import settings
from app.logger import logger
from app.models.chat_models import SearchResult
from app.services.retrieval_ports import EmbeddingService
from app.services.search_service import SearchService


class MongoVectorStore:
    """Retrieve documents by similarity through Atlas Vector Search."""

    def __init__(self, search_service: SearchService, embedding_service: EmbeddingService):
        """Reuse SearchService's connected collection and the embedding service."""
        self.search_service = search_service
        self.embedding_service = embedding_service

    async def similarity_search(
        self,
        query: str,
        limit: int = 5,
        owner_id: str | None = None,
    ) -> list[SearchResult]:
        """Embed the query and search the configured Atlas vector index."""
        collection = self.search_service.collection
        if collection is None:
            raise RuntimeError("MongoDB Atlas is not available for vector search.")

        try:
            query_embedding = await self.embedding_service.embed_query(query)
        except Exception as exc:
            logger.bind(reason=str(exc)).warning("Query embedding failed; skipping vector search.")
            raise RuntimeError("Query embedding failed.") from exc

        try:
            vector_limit = max(limit * 5, 20)
            pipeline = [
                {
                    "$vectorSearch": {
                        "index": settings.mongodb_vector_index,
                        "path": "embedding",
                        "queryVector": query_embedding,
                        "numCandidates": max(vector_limit * 10, 50),
                        "limit": vector_limit,
                    }
                },
                {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
            ]
            access_filter = self.search_service._search_access_filter(owner_id)
            if access_filter:
                pipeline[0]["$vectorSearch"]["filter"] = access_filter
            pipeline.append({"$limit": limit})
            hits = await asyncio.to_thread(lambda: list(collection.aggregate(pipeline)))
            return [
                SearchResult(
                    title=hit.get("title", "Untitled"),
                    snippet=hit.get("snippet", ""),
                    score=float(hit.get("score", 0.0)),
                    source=hit.get("source", "mongodb-vector"),
                    page_number=hit.get("page_number"),
                    file_name=hit.get("file_name"),
                    document_id=str(hit.get("document_id") or hit.get("_id") or "") or None,
                    embedding=hit.get("embedding"),
                )
                for hit in hits
            ]
        except Exception as exc:
            logger.bind(reason=str(exc)).warning("Vector search query failed.")
            raise RuntimeError("Vector search query failed; check index readiness and filter fields.") from exc
