"""
Service d'embeddings via le HuggingFace Router (client OpenAI déjà configuré).

Implémente le protocole `EmbeddingService` défini dans `retrieval_ports.py`,
en réutilisant le client HTTP déjà initialisé par `LLMService` (même base
URL, même clé API) pour éviter toute nouvelle dépendance ou configuration.
"""

from app.config.settings import settings
from app.logger import logger
from app.services.llm_service import LLMService


class HuggingFaceEmbeddingService:
    """Calcule des embeddings via l'endpoint `/embeddings` du HuggingFace Router."""

    def __init__(self, llm_service: LLMService):
        """Réutilise le client OpenAI déjà pointé sur le HuggingFace Router."""
        self.client = llm_service.client
        self.model = settings.embedding_model

    async def embed_query(self, text: str) -> list[float]:
        """Retourne le vecteur d'embedding pour une seule requête utilisateur."""
        vectors = await self.embed_texts([text])
        return vectors[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Calcule les embeddings de plusieurs textes en une seule requête batch."""
        if not self.client:
            raise RuntimeError("HuggingFace Router client not initialized. Check HUGGINGFACE_API_KEY.")

        logger.bind(model=self.model, batch_size=len(texts)).info(
            "Requesting embeddings from HuggingFace Router."
        )
        response = self.client.embeddings.create(model=self.model, input=texts)
        return [item.embedding for item in response.data]
