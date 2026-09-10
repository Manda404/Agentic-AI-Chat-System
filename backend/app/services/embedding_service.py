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

import math

import httpx

from app.config.settings import settings
from app.logger import logger

FEATURE_EXTRACTION_URL = "https://router.huggingface.co/hf-inference/models/{model}/pipeline/feature-extraction"


def validate_embeddings(vectors, count: int, dimensions: int) -> None:
    """Refuse les réponses partielles, token embeddings et vecteurs invalides."""
    if not isinstance(vectors, list) or len(vectors) != count:
        raise ValueError("Embedding response count does not match input count.")
    for vector in vectors:
        if not isinstance(vector, list) or len(vector) != dimensions:
            raise ValueError("Embedding dimensions do not match EMBEDDING_DIMENSIONS.")
        if any(isinstance(x, bool) or not isinstance(x, (int, float)) or not math.isfinite(x) for x in vector):
            raise ValueError("Embedding contains non-finite or non-numeric values.")
        if not any(vector):
            raise ValueError("Embedding must not be a zero vector.")


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
        if not texts:
            return []
        if not self.api_key:
            raise RuntimeError("HUGGINGFACE_API_KEY not set. Check your .env file.")
        url = FEATURE_EXTRACTION_URL.format(model=self.model)
        vectors = []
        async with httpx.AsyncClient(timeout=30.0) as client:
            for start in range(0, len(texts), 32):
                batch = texts[start:start + 32]
                response = await client.post(
                    url,
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"inputs": batch},
                )
                response.raise_for_status()
                payload = response.json()
                validate_embeddings(payload, len(batch), settings.embedding_dimensions)
                vectors.extend(payload)
        return vectors
