"""Experimental corrective RAG. Assess passage usefulness, filter weak evidence and rewrite the query when initial context is insufficient."""

import re
from dataclasses import dataclass

from app.logger import logger
from app.models.chat_models import AgentResult, CorrectiveRAGReview, SearchResult
from app.services.llm_service import LLMService
from app.state import GraphState


@dataclass(frozen=True)
class DocumentGrade:
    """Local fallback score for one candidate document."""

    document: SearchResult
    label: str
    verdict: str
    relevance: float
    matched_terms: list[str]
    reason: str


class CorrectiveRAGAgent:
    """Assess, filter and correct retrieval before grounded generation."""

    STOPWORDS = {
        "about",
        "avec",
        "cela",
        "cella",
        "cette",
        "dans",
        "does",
        "dont",
        "est",
        "for",
        "from",
        "how",
        "les",
        "par",
        "pour",
        "quoi",
        "que",
        "qui",
        "sur",
        "the",
        "une",
        "what",
        "why",
    }

    def __init__(
        self,
        llm_service: LLMService | None = None,
        min_relevance: float = 0.2,
        min_accept_confidence: float = 0.65,
    ):
        """Configure the LLM grader and deterministic fallback."""
        self.llm_service = llm_service
        self.min_relevance = min_relevance
        self.min_accept_confidence = min_accept_confidence

    async def run(self, state: GraphState) -> AgentResult:
        """Generate a CRAG decision and update workflow state."""
        documents = state.selected_documents
        if not documents:
            return self._fallback_decision(state, [], "fallback", "No retrieved documents to evaluate.")

        review, source = await self._review(state.user_message, documents)
        grade_by_label = {grade.label: grade for grade in review.grades}
        kept: list[SearchResult] = []
        normalized_grades = []
        for index, document in enumerate(documents, start=1):
            label = str(index)
            grade = grade_by_label.get(label)
            verdict = grade.verdict if grade else "irrelevant"
            relevance_score = grade.relevance_score if grade else 0.0
            if verdict == "relevant" and relevance_score >= self.min_relevance:
                kept.append(document)
            normalized_grades.append(
                {
                    "label": label,
                    "title": document.title,
                    "file_name": document.file_name,
                    "page_number": document.page_number,
                    "verdict": verdict,
                    "relevance_score": relevance_score,
                    "reason": grade.reason if grade else "Document was not graded by the evaluator.",
                }
            )

        decision = self._normalize_decision(review, kept, state)
        state.reranked_results = kept
        state.retrieval_metrics["corrective_rag"] = {
            "enabled": True,
            "source": source,
            "decision": decision,
            "confidence": review.confidence,
            "rewritten_query": review.rewritten_query if decision == "rewrite" else None,
            "input_documents": len(documents),
            "kept_documents": len(kept),
            "min_relevance": self.min_relevance,
            "grades": normalized_grades,
            "feedback": review.feedback,
        }

        if decision == "rewrite" and review.rewritten_query:
            state.metadata["retrieval_query"] = review.rewritten_query
        elif decision == "fallback":
            self._set_insufficient_evidence_answer(state)

        logger.bind(
            conversation_id=state.conversation_id,
            decision=decision,
            source=source,
            confidence=review.confidence,
            input_documents=len(documents),
            kept_documents=len(kept),
        ).info("Corrective RAG completed.")

        return AgentResult(
            agent="corrective_rag",
            output=f"CRAG decision: {decision}; kept {len(kept)}/{len(documents)} documents.",
            metadata=state.retrieval_metrics["corrective_rag"],
        )

    async def _review(self, user_message: str, documents: list[SearchResult]) -> tuple[CorrectiveRAGReview, str]:
        """Request an LLM grade, falling back to local grading if needed."""
        formatted = self._format_documents(documents)
        if self.llm_service:
            try:
                review = await self.llm_service.corrective_rag_review(user_message, formatted)
                return review, "llm"
            except Exception as exc:
                logger.bind(reason=str(exc)).warning("LLM CRAG evaluator failed; using deterministic fallback.")
        return self._local_review(user_message, documents), "fallback"

    def _normalize_decision(
        self,
        review: CorrectiveRAGReview,
        kept: list[SearchResult],
        state: GraphState,
    ) -> str:
        """Protect the workflow from inconsistent model decisions."""
        if kept and review.decision == "accept" and review.confidence >= self.min_accept_confidence:
            return "accept"
        if (
            review.decision == "rewrite"
            and review.rewritten_query
            and not state.retrieval_correction_attempted
        ):
            return "rewrite"
        if kept:
            return "accept"
        return "fallback"

    def _local_review(self, user_message: str, documents: list[SearchResult]) -> CorrectiveRAGReview:
        """Use lexical grading when the model is unavailable."""
        grades = self._grade_documents(user_message, documents)
        relevant = [grade for grade in grades if grade.verdict == "relevant"]
        if relevant:
            decision = "accept"
            confidence = max(grade.relevance for grade in relevant)
            rewritten_query = None
        elif grades:
            decision = "rewrite"
            confidence = max(grade.relevance for grade in grades)
            rewritten_query = self._rewrite_query(user_message)
        else:
            decision = "fallback"
            confidence = 0.0
            rewritten_query = None
        return CorrectiveRAGReview(
            decision=decision,
            confidence=round(confidence, 4),
            rewritten_query=rewritten_query,
            grades=[
                {
                    "label": grade.label,
                    "verdict": grade.verdict,
                    "relevance_score": grade.relevance,
                    "reason": grade.reason,
                }
                for grade in grades
            ],
            feedback="Deterministic CRAG fallback used lexical overlap and retrieval score.",
        )

    def _fallback_decision(
        self,
        state: GraphState,
        grades: list[dict],
        decision: str,
        feedback: str,
    ) -> AgentResult:
        """Record a CRAG decision when no documents are available."""
        state.retrieval_metrics["corrective_rag"] = {
            "enabled": True,
            "source": "fallback",
            "decision": decision,
            "confidence": 0.0,
            "rewritten_query": None,
            "input_documents": 0,
            "kept_documents": 0,
            "min_relevance": self.min_relevance,
            "grades": grades,
            "feedback": feedback,
        }
        self._set_insufficient_evidence_answer(state)
        return AgentResult(
            agent="corrective_rag",
            output=f"CRAG decision: {decision}; kept 0/0 documents.",
            metadata=state.retrieval_metrics["corrective_rag"],
        )

    def _set_insufficient_evidence_answer(self, state: GraphState) -> None:
        fallback = (
            "I could not find sufficiently relevant indexed documents for this question. "
            "Please ingest a more relevant document or rephrase the request with more specific terms."
        )
        state.rag_output = fallback
        state.draft_answer = fallback
        state.compressed_context = ""

    def _format_documents(self, documents: list[SearchResult]) -> str:
        """Format candidates with stable labels for the CRAG grader."""
        blocks = []
        for index, item in enumerate(documents, start=1):
            location = []
            if item.file_name:
                location.append(item.file_name)
            if item.page_number is not None:
                location.append(f"page {item.page_number}")
            location_text = f" ({', '.join(location)})" if location else ""
            blocks.append(
                f"[{index}] {item.title}{location_text}\n"
                f"Score: {item.score}\n"
                f"Snippet: {item.snippet[:1200]}"
            )
        return "\n\n".join(blocks)

    def _grade_documents(self, user_message: str, documents: list[SearchResult]) -> list[DocumentGrade]:
        """Assign a bounded relevance score from query-term overlap."""
        query_terms = self._terms(user_message)
        grades: list[DocumentGrade] = []
        for index, item in enumerate(documents, start=1):
            text = f"{item.title} {item.snippet}".lower()
            matched_terms = sorted(term for term in query_terms if term in text)
            score_signal = max(0.0, min(float(item.score), 2.0)) / 2.0
            if query_terms:
                overlap = len(matched_terms) / max(1, min(len(query_terms), 8))
                relevance = (overlap * 0.85) + (score_signal * 0.15)
            else:
                relevance = score_signal
            relevance = round(relevance, 4)
            verdict = "relevant" if relevance >= self.min_relevance else "ambiguous" if relevance >= 0.1 else "irrelevant"
            reason = (
                f"Matched terms: {', '.join(matched_terms)}."
                if matched_terms
                else "No strong query term overlap found."
            )
            grades.append(
                DocumentGrade(
                    document=item,
                    label=str(index),
                    verdict=verdict,
                    relevance=relevance,
                    matched_terms=matched_terms,
                    reason=reason,
                )
            )
        grades.sort(key=lambda grade: grade.relevance, reverse=True)
        return grades

    def _rewrite_query(self, user_message: str) -> str:
        """Build a compact fallback query when the model is unavailable."""
        terms = sorted(self._terms(user_message))
        return " ".join(terms[:10]) or user_message

    def _terms(self, text: str) -> set[str]:
        """Extract meaningful terms for retrieval correction."""
        return {
            term
            for term in re.findall(r"[a-zA-Z0-9_]+", text.lower())
            if len(term) > 2 and term not in self.STOPWORDS
        }
