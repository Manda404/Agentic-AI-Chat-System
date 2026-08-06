"""
Service d'embeddings via HuggingFace Inference Providers (pipeline feature-extraction).

Le endpoint OpenAI-compatible `/v1/embeddings` du HuggingFace Router ne
dessert aucun modèle d'embedding testé (404 sur bge-small-en-v1.5,
all-MiniLM-L6-v2, bge-m3...). La route qui fonctionne réellement est la
route "pipeline" du provider hf-inference, exposée sous
`router.huggingface.co/hf-inference/models/{model}/pipeline/feature-extraction`
(vérifié manuellement : 200 avec un vecteur par texte en entrée).

Implémente le protocole `EmbeddingService` défini dans `retrieval_ports.py`.
"""

import httpx

from app.config.settings import settings
from app.logger import logger

FEATURE_EXTRACTION_URL = "https://router.huggingface.co/hf-inference/models/{model}/pipeline/feature-extraction"


class HuggingFaceEmbeddingService:
    """Calcule des embeddings via la route pipeline feature-extraction du HuggingFace Router."""

    def __init__(self):
        """Lit le modèle d'embedding et la clé API directement depuis `settings`."""
        self.model = settings.embedding_model
        self.api_key = settings.huggingface_api_key

    async def embed_query(self, text: str) -> list[float]:
        """Retourne le vecteur d'embedding pour une seule requête utilisateur."""
        vectors = await self.embed_texts([text])
        return vectors[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Calcule les embeddings de plusieurs textes en un seul appel batch."""
        if not self.api_key:
            raise RuntimeError("HUGGINGFACE_API_KEY not set. Check your .env file.")

        logger.bind(model=self.model, batch_size=len(texts)).info(
            "Requesting embeddings from HuggingFace Inference Providers."
        )
        url = FEATURE_EXTRACTION_URL.format(model=self.model)
        async with httpx.AsyncClient(timeout=30.0) as client:
            response = await client.post(
                url,
                headers={"Authorization": f"Bearer {self.api_key}"},
                json={"inputs": texts},
            )
            response.raise_for_status()
            return response.json()
