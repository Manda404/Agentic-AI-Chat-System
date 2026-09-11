"""Local extractive context compression that preserves evidence labels and bounds context size."""

import re

from app.logger import logger
from app.models.chat_models import AgentResult, SearchResult
from app.services.llm_service import LLMService
from app.state import GraphState


class ContextCompressionAgent:
    """Reduce LLM snippets while retaining source metadata."""

    def __init__(self, llm_service: LLMService, max_chars: int = 4000, use_llm: bool = False):
        """Configure max_chars and optional LLM compression through llm_service and use_llm."""
        self.llm_service = llm_service
        self.max_chars = max_chars
        self.use_llm = use_llm

    async def run(self, state: GraphState) -> AgentResult:
        """Compress selected documents and populate state.compressed_context."""
        documents = state.selected_documents
        formatted = self._format_documents(documents)
        if self.use_llm and formatted:
            try:
                # Optional advanced mode: ask the LLM to retain useful passages.
                compressed = await self.llm_service.compress_context(
                    user_message=state.user_message,
                    documents=formatted,
                    max_chars=self.max_chars,
                )
            except Exception as exc:
                logger.bind(reason=str(exc)).warning("LLM context compression failed; using local compression.")
                compressed = self._local_compress(documents)
        else:
            compressed = self._local_compress(documents, state.user_message)

        state.compressed_context = compressed[: self.max_chars]
        labels = {int(label) for label in re.findall(r"^\[(\d+)\]", state.compressed_context, re.MULTILINE)}
        # Local compression retains a contiguous prefix of candidates.
        count = 0
        while count + 1 in labels:
            count += 1
        state.metadata["context_document_count"] = count
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
        """Format documents with source labels before optional LLM compression."""
        return "\n\n".join(
            f"[{index}] {item.title} ({item.file_name or item.source}, page {item.page_number})\n{item.snippet}"
            for index, item in enumerate(documents, start=1)
        )

    def _local_compress(self, documents: list[SearchResult], user_message: str = "") -> str:
        """Deterministically retain titles, files and pages while shortening snippets to fit max_chars."""
        query_terms = self._terms(user_message)
        chunks: list[str] = []
        remaining = self.max_chars
        for index, item in enumerate(documents, start=1):
            # Preserve source labels for grounded citations.
            label = f"[{index}] {item.title}"
            if item.file_name:
                label += f" ({item.file_name}"
                if item.page_number is not None:
                    label += f", page {item.page_number}"
                label += ")"
            snippet_budget = min(900, remaining - len(label) - 1)
            if snippet_budget <= 0:
                break
            snippet = self._select_evidence(item.snippet, query_terms, snippet_budget)
            block = f"{label}\n{snippet}"
            if len(block) > remaining:
                break
            chunks.append(block)
            remaining -= len(block) + 2
            if remaining <= 200:
                break
        return "\n\n".join(chunks)

    def _select_evidence(self, snippet: str, query_terms: set[str], budget: int) -> str:
        """Select relevant sentences rather than only the beginning of the passage."""
        text = " ".join(snippet.split())
        if len(text) <= budget or not query_terms:
            return text[:budget].strip()

        sentences = [sentence.strip() for sentence in re.split(r"(?<=[.!?])\s+", text) if sentence.strip()]
        if not sentences:
            return text[:budget].strip()

        scored = []
        for position, sentence in enumerate(sentences):
            lowered = sentence.lower()
            overlap = sum(1 for term in query_terms if term in lowered)
            score = overlap * 10 - position
            scored.append((score, position, sentence))

        selected: list[tuple[int, str]] = []
        used = 0
        for score, position, sentence in sorted(scored, key=lambda item: item[0], reverse=True):
            if score <= 0 and selected:
                break
            next_size = len(sentence) + (1 if selected else 0)
            if used + next_size > budget:
                continue
            selected.append((position, sentence))
            used += next_size
            if used >= budget * 0.8:
                break

        if not selected:
            return text[:budget].strip()
        return " ".join(sentence for _, sentence in sorted(selected)).strip()

    def _terms(self, text: str) -> set[str]:
        """Extract sufficiently long terms to guide local compression."""
        return {term for term in re.findall(r"[a-zA-Z0-9_]+", text.lower()) if len(term) > 2}
