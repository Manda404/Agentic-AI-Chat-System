"""
Store vectoriel basé sur MongoDB Atlas Vector Search.

Implémente `VectorStorePort` (voir `retrieval_ports.py`) en réutilisant la
collection pymongo déjà connectée par `SearchService` (même cluster, mêmes
documents, un seul point de connexion) et un `EmbeddingService` pour
vectoriser la requête utilisateur.

`pymongo` est synchrone : `aggregate()` bloque le thread appelant. L'appel
est délégué à `asyncio.to_thread` pour ne pas geler l'event loop pendant la
requête `$vectorSearch`.
"""

import asyncio

from app.config.settings import settings
from app.logger import logger
from app.models.chat_models import SearchResult
from app.services.retrieval_ports import EmbeddingService
from app.services.search_service import SearchService


class MongoVectorStore:
    """Recherche par similarité vectorielle via l'index Atlas Vector Search."""

    def __init__(self, search_service: SearchService, embedding_service: EmbeddingService):
        """Réutilise la collection déjà connectée par `SearchService` et un service d'embeddings."""
        self.search_service = search_service
        self.embedding_service = embedding_service

    async def similarity_search(self, query: str, limit: int = 5) -> list[SearchResult]:
        """Vectorise la requête puis interroge l'index Atlas Vector Search."""
        collection = self.search_service.collection
        if collection is None:
            return []

        try:
            query_embedding = await self.embedding_service.embed_query(query)
        except Exception as exc:
            logger.bind(reason=str(exc)).warning("Query embedding failed; skipping vector search.")
            return []

        try:
            pipeline = [
                {
                    "$vectorSearch": {
                        "index": settings.mongodb_vector_index,
                        "path": "embedding",
                        "queryVector": query_embedding,
                        "numCandidates": max(limit * 10, 50),
                        "limit": limit,
                    }
                },
                {"$addFields": {"score": {"$meta": "vectorSearchScore"}}},
            ]
            hits = await asyncio.to_thread(lambda: list(collection.aggregate(pipeline)))
            return [
                SearchResult(
                    title=hit.get("title", "Untitled"),
                    snippet=hit.get("snippet", ""),
                    score=float(hit.get("score", 0.0)),
                    source=hit.get("source", "mongodb-vector"),
                    page_number=hit.get("page_number"),
                    file_name=hit.get("file_name"),
                )
                for hit in hits
            ]
        except Exception as exc:
            logger.bind(reason=str(exc)).warning("Vector search query failed.")
            return []
