"""Hugging Face feature-extraction embeddings. Use router.huggingface.co/hf-inference/models/{model}/pipeline/feature-extraction. Earlier project checks received 404 from OpenAI-compatible /v1/embeddings for tested models, while the feature-extraction pipeline returned one vector per input. Implements the EmbeddingService protocol; actual provider/model availability must still be verified for the account."""

import math

import httpx

from app.config.settings import settings
from app.logger import logger

FEATURE_EXTRACTION_URL = "https://router.huggingface.co/hf-inference/models/{model}/pipeline/feature-extraction"


def validate_embeddings(vectors, count: int, dimensions: int) -> None:
    """Reject incomplete responses, token-level embeddings and invalid vectors."""
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
    """Compute embeddings through Hugging Face's feature-extraction pipeline."""

    def __init__(self):
        """Read the embedding model and API key from settings."""
        self.model = settings.embedding_model
        self.api_key = settings.huggingface_api_key

    async def embed_query(self, text: str) -> list[float]:
        """Return the embedding vector of one user query."""
        vectors = await self.embed_texts([text])
        return vectors[0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        """Embed multiple texts in one batch request."""
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
