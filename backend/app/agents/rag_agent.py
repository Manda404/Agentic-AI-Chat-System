"""Grounded generation for the baseline RAG workflow after retrieval, reranking and compression. Add source metadata to the generated answer; local validation controls publication."""

from app.logger import logger
from app.models.chat_models import AgentResult
from app.services.llm_service import LLMService
from app.state import GraphState


class RAGAgent:
    """Generate a documented answer from retrieved results."""

    def __init__(self, llm_service: LLMService):
        """Inject the LLM service used for grounded generation."""
        self.llm_service = llm_service

    async def run(self, state: GraphState) -> AgentResult:
        """Select retained documents, build evidence context, generate an answer and attach sources. Populate rag_output and draft_answer; report unavailable generation or missing evidence explicitly."""
        documents = state.selected_documents
        if not documents:
            # Report missing evidence explicitly instead of fabricating an answer.
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

        # History is secondary context, never documentary evidence.
        conversation_history = "\n".join(
            f"{message.get('role', 'unknown')}: {message.get('content', '')}"
            for message in state.conversation_context
        )
        # Prefer compressed context to bound the prompt size.
        retrieved_documents = state.compressed_context or self._format_retrieved_documents(documents)

        if state.correction_attempted and state.critic_feedback:
            conversation_history += (
                "\nPrevious draft (to revise):\n" + (state.draft_answer or "")
                + "\nQuality feedback: " + state.critic_feedback
            )

        try:
            # The LLM must answer only from the retrieved context.
            answer = await self.llm_service.grounded_answer(
                question=state.user_message,
                retrieved_documents=retrieved_documents,
                conversation_history=conversation_history,
            )
            state.rag_output = self._append_sources(answer.strip(), state)
            state.draft_answer = state.rag_output
            metadata = {
                "grounded": True,
                "sources_count": len(documents),
                "document_ids": [item.document_id for item in documents if item.document_id],
            }
        except Exception as exc:
            logger.bind(conversation_id=state.conversation_id, reason=str(exc)).exception(
                "RAG generation failed; falling back to search output."
            )
            # On provider failure, retain retrieval diagnostics instead of crashing.
            state.rag_output = self._append_sources(
                "Generation is unavailable. Here are the retrieved excerpts:\n\n" + retrieved_documents,
                state,
            )
            state.draft_answer = state.rag_output
            metadata = {"grounded": False, "fallback": True, "reason": "llm_unavailable"}

        logger.bind(
            conversation_id=state.conversation_id,
            output_length=len(state.rag_output or ""),
            sources_count=len(documents),
        ).info("RAG agent completed.")

        return AgentResult(agent="rag", output=state.rag_output or "", metadata=metadata)

    def _format_retrieved_documents(self, documents) -> str:
        """Format retrieved passages with numbered labels and source metadata."""
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
                f"Document ID: {item.document_id or 'unknown'}\n"
                f"Score: {item.score}\n"
                f"Snippet: {item.snippet}"
            )
        return "\n\n".join(lines)

    def _append_sources(self, answer: str, state: GraphState) -> str:
        """Append the selected documents as numbered sources to the answer."""
        source_lines = []
        for index, item in enumerate(state.selected_documents, start=1):
            source = f"- [{index}] {item.title}"
            if item.page_number is not None:
                source += f", page {item.page_number}"
            if item.file_name:
                source += f" ({item.file_name})"
            source_lines.append(source)

        if not source_lines:
            return answer
        return f"{answer}\n\nSources:\n" + "\n".join(source_lines)
