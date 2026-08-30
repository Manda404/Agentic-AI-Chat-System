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

RRF_K = 60.0


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
            vector_results = await self.vector_store.similarity_search(
                state.user_message,
                limit=self.limit,
                owner_id=state.metadata.get("user_id"),
            )
        except Exception as exc:
            logger.bind(reason=str(exc)).warning("Vector search failed; continuing with full-text results.")
            vector_results = []

        # Fusionne par rang, car les scores full-text et vectoriels ne partagent pas la même échelle.
        merged = self._merge(full_text_results, vector_results)
        state.search_results = merged[: self.limit]
        state.retrieval_metrics.update(
            {
                "full_text_count": len(full_text_results),
                "vector_count": len(vector_results),
                "hybrid_count": len(state.search_results),
                "hybrid_fusion": "rrf",
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
        """Fusionne full-text et vectoriel avec Reciprocal Rank Fusion."""
        fused: dict[tuple[str, str, int | None], tuple[SearchResult, float]] = {}
        for results in (full_text, vector):
            for rank, item in enumerate(results, start=1):
                key = self._key(item)
                current_item, current_score = fused.get(key, (item, 0.0))
                if item.snippet and len(item.snippet) > len(current_item.snippet):
                    current_item = item
                fused[key] = (current_item, current_score + 1.0 / (RRF_K + rank))

        ranked = sorted(fused.values(), key=lambda pair: pair[1], reverse=True)
        return [
            item.model_copy(update={"score": fused_score})
            for item, fused_score in ranked
        ]

    def _key(self, item: SearchResult) -> tuple[str, str, int | None]:
        """Construit une clé stable de document pour déduplication inter-branches."""
        if item.document_id:
            return (item.document_id, "", None)
        return (item.title, item.file_name or item.source, item.page_number)
