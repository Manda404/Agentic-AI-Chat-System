"""
Agent de compression de contexte RAG.

Avant d'envoyer les documents au LLM, le projet réduit les snippets pour
maîtriser les coûts, éviter les prompts trop longs et garder uniquement un
contexte utile. L'agent peut utiliser un LLM de compression, mais le mode par
défaut reste local pour ne pas ajouter un appel LLM obligatoire.
"""

from app.logger import logger
from app.models.chat_models import AgentResult, SearchResult
from app.services.llm_service import LLMService
from app.state import GraphState


class ContextCompressionAgent:
    """Réduit les snippets envoyés au LLM tout en gardant les métadonnées source."""

    def __init__(self, llm_service: LLMService, max_chars: int = 4000, use_llm: bool = False):
        """
        Configure la stratégie de compression.

        Args:
            llm_service: Service utilisé si `use_llm=True`.
            max_chars: Taille maximale du contexte final.
            use_llm: Active une compression LLM optionnelle.
        """
        self.llm_service = llm_service
        self.max_chars = max_chars
        self.use_llm = use_llm

    async def run(self, state: GraphState) -> AgentResult:
        """Compresse les documents rerankés et écrit `state.compressed_context`."""
        documents = state.reranked_results or state.search_results
        formatted = self._format_documents(documents)
        if self.use_llm and formatted:
            try:
                # Mode avancé optionnel : demander au LLM de garder les passages utiles.
                compressed = await self.llm_service.compress_context(
                    user_message=state.user_message,
                    documents=formatted,
                    max_chars=self.max_chars,
                )
            except Exception as exc:
                logger.bind(reason=str(exc)).warning("LLM context compression failed; using local compression.")
                compressed = self._local_compress(documents)
        else:
            compressed = self._local_compress(documents)

        state.compressed_context = compressed[: self.max_chars]
        state.retrieval_metrics["compressed_context_chars"] = len(state.compressed_context)

        logger.bind(
            conversation_id=state.conversation_id,
            context_chars=len(state.compressed_context),
            documents_count=len(documents),
        ).info("Context compression completed.")

        return AgentResult(
            agent="context_compression",
            output=state.compressed_context or "No context available.",
            metadata={"compressed_context_chars": len(state.compressed_context or "")},
        )

    def _format_documents(self, documents: list[SearchResult]) -> str:
        """Formate les documents avec leurs labels source avant compression LLM éventuelle."""
        return "\n\n".join(
            f"[{index}] {item.title} ({item.file_name or item.source}, page {item.page_number})\n{item.snippet}"
            for index, item in enumerate(documents, start=1)
        )

    def _local_compress(self, documents: list[SearchResult]) -> str:
        """
        Compression locale déterministe.

        Elle garde les titres, fichiers et pages, puis tronque progressivement
        les snippets pour respecter `max_chars`.
        """
        chunks: list[str] = []
        remaining = self.max_chars
        for index, item in enumerate(documents, start=1):
            # Le label source est conservé pour que RAGAgent puisse citer clairement.
            label = f"[{index}] {item.title}"
            if item.file_name:
                label += f" ({item.file_name}"
                if item.page_number is not None:
                    label += f", page {item.page_number}"
                label += ")"
            snippet_budget = max(200, min(900, remaining - len(label) - 8))
            snippet = item.snippet[:snippet_budget].strip()
            block = f"{label}\n{snippet}"
            if len(block) > remaining:
                break
            chunks.append(block)
            remaining -= len(block) + 2
            if remaining <= 200:
                break
        return "\n\n".join(chunks)
