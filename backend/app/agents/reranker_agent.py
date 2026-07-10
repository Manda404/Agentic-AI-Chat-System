"""
Agent de reranking documentaire.

Dans un RAG production-grade, le retrieval brut est rarement suffisant :
il faut filtrer, réordonner et limiter les documents avant de les envoyer au
LLM. Ce reranker reste léger et heuristique, mais il isole déjà cette étape
pour pouvoir brancher plus tard un cross-encoder ou un reranker LLM.
"""

import re

from app.logger import logger
from app.models.chat_models import AgentResult, SearchResult
from app.state import GraphState


class RerankerAgent:
    """Filtre et réordonne les résultats sans dépendance externe lourde."""

    def __init__(self, min_score: float = 0.0, max_results: int = 5):
        """Définit le score minimal accepté et le nombre final de documents RAG."""
        self.min_score = min_score
        self.max_results = max_results

    async def run(self, state: GraphState) -> AgentResult:
        """
        Calcule un score reranké puis écrit `state.reranked_results`.

        Le score combine le score Elasticsearch et un bonus simple si les mots
        de la question apparaissent dans le titre ou le snippet.
        """
        query_terms = self._terms(state.user_message)
        # On conserve uniquement les documents au-dessus du seuil minimal.
        scored = [
            (self._score(item, query_terms), item)
            for item in state.search_results
            if item.score >= self.min_score
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
            }
        )

        logger.bind(
            conversation_id=state.conversation_id,
            retrieved_count=len(state.search_results),
            reranked_count=len(state.reranked_results),
            top_score=top_score,
        ).info("Reranker completed.")

        return AgentResult(
            agent="reranker",
            output=f"Reranked {len(state.reranked_results)} documents.",
            metadata=state.retrieval_metrics,
        )

    def _terms(self, text: str) -> set[str]:
        """Extrait des termes simples de la question pour calculer un recouvrement lexical."""
        return {term for term in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if len(term) > 2}

    def _score(self, item: SearchResult, query_terms: set[str]) -> float:
        """Combine score de recherche et présence des termes utilisateur dans le document."""
        text = f"{item.title} {item.snippet}".lower()
        overlap = sum(1 for term in query_terms if term in text)
        return float(item.score) + overlap * 0.25
