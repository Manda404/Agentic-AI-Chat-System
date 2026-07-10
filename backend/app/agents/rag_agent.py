"""
Agent RAG : génération de réponse ancrée dans les documents.

Le RAGAgent est appelé après la recherche, le retrieval hybride, le reranking
et la compression de contexte. Son rôle est de demander au LLM une réponse qui
s'appuie sur les documents disponibles, puis d'ajouter les sources visibles
pour le frontend et pour le critic.
"""

from app.logger import logger
from app.models.chat_models import AgentResult
from app.services.llm_service import LLMService
from app.state import GraphState


class RAGAgent:
    """Produit une réponse documentée à partir des résultats récupérés."""

    def __init__(self, llm_service: LLMService):
        """Injecte le service LLM utilisé pour générer la réponse groundée."""
        self.llm_service = llm_service

    async def run(self, state: GraphState) -> AgentResult:
        """
        Génère une réponse RAG et met à jour `rag_output` / `draft_answer`.

        Étapes :
        1. choisir les documents rerankés si disponibles ;
        2. construire le contexte documentaire ;
        3. appeler `LLMService.grounded_answer` ;
        4. ajouter les sources ;
        5. fournir un fallback clair si aucun document ou si le LLM échoue.
        """
        documents = state.reranked_results or state.search_results
        if not documents:
            # Ne pas halluciner : sans document, on annonce explicitement la limite.
            fallback = (
                "I could not find relevant indexed documents for this question. "
                "Please ingest documents or rephrase the request."
            )
            state.rag_output = fallback
            state.draft_answer = fallback
            logger.bind(conversation_id=state.conversation_id).info("RAG agent completed without documents.")
            return AgentResult(
                agent="rag",
                output=fallback,
                metadata={"grounded": False, "reason": "no_documents"},
            )

        # L'historique est fourni comme contexte secondaire, jamais comme source documentaire.
        conversation_history = "\n".join(
            f"{message.get('role', 'unknown')}: {message.get('content', '')}"
            for message in state.conversation_context
        )
        # Le contexte compressé est prioritaire pour maîtriser la taille du prompt.
        retrieved_documents = state.compressed_context or self._format_retrieved_documents(documents)

        try:
            # Chemin nominal : le LLM répond uniquement depuis le contexte récupéré.
            answer = await self.llm_service.grounded_answer(
                question=state.user_message,
                retrieved_documents=retrieved_documents,
                conversation_history=conversation_history,
            )
            state.rag_output = self._append_sources(answer.strip(), state)
            state.draft_answer = state.rag_output
            metadata = {"grounded": True, "sources_count": len(state.search_results)}
        except Exception as exc:
            logger.bind(conversation_id=state.conversation_id, reason=str(exc)).exception(
                "RAG generation failed; falling back to search output."
            )
            # En cas de panne LLM, on préfère exposer le résultat documentaire plutôt que planter.
            state.rag_output = self._append_sources(
                state.search_output or "Documents were found, but the grounded answer could not be generated.",
                state,
            )
            state.draft_answer = state.rag_output
            metadata = {"grounded": False, "fallback": True, "reason": "llm_unavailable"}

        logger.bind(
            conversation_id=state.conversation_id,
            output_length=len(state.rag_output or ""),
            sources_count=len(state.search_results),
        ).info("RAG agent completed.")

        return AgentResult(agent="rag", output=state.rag_output or "", metadata=metadata)

    def _format_retrieved_documents(self, documents) -> str:
        """Transforme les documents structurés en contexte textuel lisible par le LLM."""
        lines = []
        for index, item in enumerate(documents, start=1):
            location = []
            if item.file_name:
                location.append(item.file_name)
            if item.page_number is not None:
                location.append(f"page {item.page_number}")
            location_text = f" ({', '.join(location)})" if location else ""
            lines.append(
                f"[{index}] {item.title}{location_text}\n"
                f"Score: {item.score}\n"
                f"Snippet: {item.snippet}"
            )
        return "\n\n".join(lines)

    def _append_sources(self, answer: str, state: GraphState) -> str:
        """Ajoute une section `Sources` à partir des meilleurs documents disponibles."""
        source_lines = []
        for item in (state.reranked_results or state.search_results)[:3]:
            source = f"- {item.title}"
            if item.page_number is not None:
                source += f", page {item.page_number}"
            if item.file_name:
                source += f" ({item.file_name})"
            source_lines.append(source)

        if not source_lines:
            return answer
        return f"{answer}\n\nSources:\n" + "\n".join(source_lines)
