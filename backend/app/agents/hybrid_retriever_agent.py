"""
Agent de retrieval hybride.

Ce module prépare une architecture RAG plus avancée que la recherche full-text
pure. Aujourd'hui, il fusionne les résultats MongoDB Atlas Search déjà présents dans
`state.search_results` avec un éventuel `VectorStorePort`. Par défaut, le store
vectoriel est `NullVectorStore`, donc aucune dépendance lourde n'est imposée.
"""

from app.logger import logger
from app.models.chat_models import AgentResult, SearchResult
from app.services.retrieval_ports import NullVectorStore, VectorStorePort
from app.state import GraphState


class HybridRetrieverAgent:
    """
    Fusionne les documents candidats provenant de plusieurs sources.

    Le but est d'avoir une étape dédiée où brancher plus tard embeddings,
    recherche vectorielle, hybrid search ou fusion de scores sans modifier
    `SearchAgent` ni `RAGAgent`.
    """

    def __init__(self, vector_store: VectorStorePort | None = None, limit: int = 8):
        """Configure le store vectoriel optionnel et le nombre maximum de résultats conservés."""
        self.vector_store = vector_store or NullVectorStore()
        self.limit = limit

    async def run(self, state: GraphState) -> AgentResult:
        """Fusionne full-text + vectoriel, met à jour l'état et expose des métriques de retrieval."""
        full_text_results = state.search_results or []
        try:
            # Recherche vectorielle optionnelle : peut être branchée plus tard via VectorStorePort.
            vector_results = await self.vector_store.similarity_search(state.user_message, limit=self.limit)
        except Exception as exc:
            logger.bind(reason=str(exc)).warning("Vector search failed; continuing with full-text results.")
            vector_results = []

        # Déduplique les sources, trie par score et borne le volume transmis au reranker.
        merged = self._merge(full_text_results, vector_results)
        state.search_results = merged[: self.limit]
        state.retrieval_metrics.update(
            {
                "full_text_count": len(full_text_results),
                "vector_count": len(vector_results),
                "hybrid_count": len(state.search_results),
            }
        )

        output = f"Hybrid retrieval returned {len(state.search_results)} normalized documents."
        logger.bind(
            conversation_id=state.conversation_id,
            full_text_count=len(full_text_results),
            vector_count=len(vector_results),
            hybrid_count=len(state.search_results),
        ).info("Hybrid retriever completed.")

        return AgentResult(agent="hybrid_retriever", output=output, metadata=state.retrieval_metrics)

    def _merge(self, full_text: list[SearchResult], vector: list[SearchResult]) -> list[SearchResult]:
        """Déduplique les résultats full-text/vectoriels et les trie par score décroissant."""
        seen: set[tuple[str, str, int | None]] = set()
        merged: list[SearchResult] = []
        for item in [*full_text, *vector]:
            key = (item.title, item.file_name or item.source, item.page_number)
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
        return sorted(merged, key=lambda item: item.score, reverse=True)
