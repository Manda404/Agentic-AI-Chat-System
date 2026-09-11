"""Document reranking after initial retrieval. Filter, reorder and limit candidates using lexical signals, optionally enriched by embedding cosine similarity. Stored embeddings are reused and provider failures fall back to lexical scoring."""

import math
import re

from app.logger import logger
from app.models.chat_models import AgentResult, SearchResult
from app.services.retrieval_ports import EmbeddingService
from app.state import GraphState

SEMANTIC_WEIGHT = 2.0


class RerankerAgent:
    """Filter and reorder results with lexical fallback."""

    def __init__(
        self,
        min_score: float = 0.0,
        max_results: int = 5,
        embedding_service: EmbeddingService | None = None,
    ):
        """Configure the minimum accepted score, final document count and optional embedding service for semantic scoring."""
        self.min_score = min_score
        self.max_results = max_results
        self.embedding_service = embedding_service

    async def run(self, state: GraphState) -> AgentResult:
        """Compute ranking scores and populate state.reranked_results using retrieval score, lexical overlap and optional semantic similarity."""
        query = state.metadata.get("retrieval_query") or state.user_message
        query_terms = self._terms(query)
        candidates = [item for item in state.search_results if item.score >= self.min_score]
        lexical_scores = [self._lexical_score(item, query_terms) for item in candidates]

        semantic_scores, semantic_used = await self._semantic_scores(query, candidates)

        scored = [
            (lexical + (semantic_scores[i] * SEMANTIC_WEIGHT if semantic_scores else 0.0), item)
            for i, (lexical, item) in enumerate(zip(lexical_scores, candidates))
        ]
        scored.sort(key=lambda pair: pair[0], reverse=True)
        state.reranked_results = [item for _, item in scored[: self.max_results]]

        top_score = scored[0][0] if scored else 0.0
        sources_used = [
            {
                "title": item.title,
                "file_name": item.file_name,
                "page_number": item.page_number,
                "score": item.score,
            }
            for item in state.reranked_results
        ]
        state.retrieval_metrics.update(
            {
                "retrieved_count": len(state.search_results),
                "reranked_count": len(state.reranked_results),
                "top_score": top_score,
                "sources_used": sources_used,
                "semantic_reranking_used": semantic_used,
            }
        )

        logger.bind(
            conversation_id=state.conversation_id,
            retrieved_count=len(state.search_results),
            reranked_count=len(state.reranked_results),
            top_score=top_score,
            semantic_reranking_used=semantic_used,
        ).info("Reranker completed.")

        return AgentResult(
            agent="reranker",
            output=f"Reranked {len(state.reranked_results)} documents.",
            metadata=state.retrieval_metrics,
        )

    async def _semantic_scores(
        self, user_message: str, candidates: list[SearchResult]
    ) -> tuple[list[float], bool]:
        """Compute per-document cosine similarity when an embedding service is configured."""
        if not self.embedding_service or not candidates:
            return [], False
        try:
            query_embedding = await self.embedding_service.embed_query(user_message)
            doc_embeddings = await self._document_embeddings(candidates)
            return [self._cosine_similarity(query_embedding, doc) for doc in doc_embeddings], True
        except Exception as exc:
            logger.bind(reason=str(exc)).warning(
                "Semantic reranking failed; falling back to lexical score only."
            )
            return [], False

    async def _document_embeddings(self, candidates: list[SearchResult]) -> list[list[float]]:
        """Reuse stored embeddings and compute only missing vectors."""
        embeddings: list[list[float] | None] = [item.embedding for item in candidates]
        missing_indexes = [index for index, embedding in enumerate(embeddings) if not embedding]
        if missing_indexes:
            texts = [f"{candidates[index].title} {candidates[index].snippet}" for index in missing_indexes]
            generated = await self.embedding_service.embed_texts(texts)
            for index, embedding in zip(missing_indexes, generated):
                embeddings[index] = embedding
        return [embedding or [] for embedding in embeddings]

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Compute cosine similarity in Python without numpy."""
        if not a or len(a) != len(b):
            raise ValueError("Incompatible embedding dimensions; re-ingest with the configured model.")
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _terms(self, text: str) -> set[str]:
        """Extract query terms for lexical overlap scoring."""
        return {term for term in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if len(term) > 2}

    def _lexical_score(self, item: SearchResult, query_terms: set[str]) -> float:
        """Combine the retrieval score with query-term occurrences in the document."""
        text = f"{item.title} {item.snippet}".lower()
        overlap = sum(1 for term in query_terms if term in text)
        return float(item.score) + overlap * 0.25
