"""Extensible interfaces for embedding providers and vector retrieval."""

from typing import Protocol

from app.models.chat_models import SearchResult


class EmbeddingService(Protocol):
    """Minimal interface for an embedding provider."""

    async def embed_query(self, text: str) -> list[float]:
        """Return one vector for a user query."""

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per text in a batch request."""


class VectorStorePort(Protocol):
    """Minimal interface for a vector retrieval implementation."""

    async def similarity_search(
        self,
        query: str,
        limit: int = 5,
        owner_id: str | None = None,
    ) -> list[SearchResult]:
        """Return documents similar to the query."""


class NullVectorStore:
    """Dependency-free fallback with no vector retrieval available."""

    async def similarity_search(
        self,
        query: str,
        limit: int = 5,
        owner_id: str | None = None,
    ) -> list[SearchResult]:
        return []
