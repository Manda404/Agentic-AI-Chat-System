"""
Agent de reranking documentaire.

Dans un RAG production-grade, le retrieval brut est rarement suffisant :
il faut filtrer, réordonner et limiter les documents avant de les envoyer au
LLM. Le score de base reste lexical (léger, sans dépendance), mais si un
`EmbeddingService` est configuré (voir `HuggingFaceEmbeddingService`), il est
combiné à une similarité cosinus calculée sur des embeddings réels. Tout
échec côté embeddings (quota, modèle indisponible, timeout) retombe
silencieusement sur le score lexical seul.
"""

import math
import re

from app.logger import logger
from app.models.chat_models import AgentResult, SearchResult
from app.services.retrieval_ports import EmbeddingService
from app.state import GraphState

SEMANTIC_WEIGHT = 2.0


class RerankerAgent:
    """Filtre et réordonne les résultats, avec repli lexical garanti."""

    def __init__(
        self,
        min_score: float = 0.0,
        max_results: int = 5,
        embedding_service: EmbeddingService | None = None,
    ):
        """Définit le score minimal accepté, le nombre final de documents RAG,
        et un service d'embeddings optionnel pour le scoring sémantique."""
        self.min_score = min_score
        self.max_results = max_results
        self.embedding_service = embedding_service

    async def run(self, state: GraphState) -> AgentResult:
        """
        Calcule un score reranké puis écrit `state.reranked_results`.

        Le score combine le score full-text (MongoDB Atlas Search), un bonus lexical si les mots
        de la question apparaissent dans le titre ou le snippet, et une
        similarité sémantique (embeddings) si disponible.
        """
        query_terms = self._terms(state.user_message)
        candidates = [item for item in state.search_results if item.score >= self.min_score]
        lexical_scores = [self._lexical_score(item, query_terms) for item in candidates]

        semantic_scores, semantic_used = await self._semantic_scores(state.user_message, candidates)

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
        """Calcule une similarité cosinus par document si un embedding service est branché."""
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
        """Réutilise les embeddings stockés et ne calcule que ceux qui manquent."""
        embeddings: list[list[float] | None] = [item.embedding for item in candidates]
        missing_indexes = [index for index, embedding in enumerate(embeddings) if not embedding]
        if missing_indexes:
            texts = [f"{candidates[index].title} {candidates[index].snippet}" for index in missing_indexes]
            generated = await self.embedding_service.embed_texts(texts)
            for index, embedding in zip(missing_indexes, generated):
                embeddings[index] = embedding
        return [embedding or [] for embedding in embeddings]

    def _cosine_similarity(self, a: list[float], b: list[float]) -> float:
        """Similarité cosinus pure Python, sans dépendance numpy."""
        dot = sum(x * y for x, y in zip(a, b))
        norm_a = math.sqrt(sum(x * x for x in a))
        norm_b = math.sqrt(sum(y * y for y in b))
        if norm_a == 0.0 or norm_b == 0.0:
            return 0.0
        return dot / (norm_a * norm_b)

    def _terms(self, text: str) -> set[str]:
        """Extrait des termes simples de la question pour calculer un recouvrement lexical."""
        return {term for term in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if len(term) > 2}

    def _lexical_score(self, item: SearchResult, query_terms: set[str]) -> float:
        """Combine score de recherche et présence des termes utilisateur dans le document."""
        text = f"{item.title} {item.snippet}".lower()
        overlap = sum(1 for term in query_terms if term in text)
        return float(item.score) + overlap * 0.25
