"""Ports extensibles pour embeddings et recherche vectorielle."""

from typing import Protocol

from app.models.chat_models import SearchResult


class EmbeddingService(Protocol):
    """Interface minimale pour brancher un fournisseur d'embeddings."""

    async def embed_query(self, text: str) -> list[float]:
        """Retourne un vecteur pour une requête utilisateur."""

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Retourne un vecteur par texte, en un seul appel batch."""


class VectorStorePort(Protocol):
    """Interface minimale pour brancher une future recherche vectorielle."""

    async def similarity_search(
        self,
        query: str,
        limit: int = 5,
        owner_id: str | None = None,
    ) -> list[SearchResult]:
        """Retourne les documents proches de la requête."""


class NullVectorStore:
    """Fallback sans dépendance : aucune recherche vectorielle disponible."""

    async def similarity_search(
        self,
        query: str,
        limit: int = 5,
        owner_id: str | None = None,
    ) -> list[SearchResult]:
        return []
