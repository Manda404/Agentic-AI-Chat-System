"""Lightweight chat-output guard. Mask recognizable API keys, bearer tokens, passwords and private keys with [REDACTED_SECRET]. An optional LLM review exists but the current workflow uses local checks. Final output is filtered before publication."""

import re

from app.logger import logger
from app.models.chat_models import AgentResult, SafetyReview
from app.services.llm_service import LLMService
from app.state import GraphState


class SafetyGuardAgent:
    """Detect recognizable secrets/tokens and optionally request an LLM review."""

    SECRET_PATTERNS = [
        re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{12,})"),
        re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-.]{20,}"),
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ]

    def __init__(self, llm_service: LLMService, use_llm: bool = False):
        """Configure the guard: llm_service is used only when use_llm enables the optional review."""
        self.llm_service = llm_service
        self.use_llm = use_llm

    async def run(self, state: GraphState) -> AgentResult:
        """Check and redact the candidate as needed; update safety_passed, safety_feedback and evaluation.safety."""
        candidate = state.final_answer or state.draft_answer or state.rag_output or state.summary_output or ""
        redacted_answer, issues = self._redact(candidate)
        review = SafetyReview(
            passed=not issues,
            issues=issues,
            redacted=bool(issues),
            feedback="No safety issue detected." if not issues else "Sensitive content was redacted.",
        )

        if self.use_llm and not issues:
            try:
                # Optional step: request a more nuanced safety review from the LLM.
                review = await self.llm_service.safety_review(redacted_answer)
            except Exception as exc:
                logger.bind(reason=str(exc)).warning("LLM safety review failed; using local safety result.")

        state.safety_passed = review.passed
        state.safety_feedback = review.feedback
        state.evaluation["safety"] = review.model_dump()
        if review.redacted:
            # Propagate redacted text to candidate fields before publication.
            state.draft_answer = redacted_answer
            state.rag_output = redacted_answer if state.rag_output else state.rag_output
            state.summary_output = redacted_answer if state.summary_output else state.summary_output
            state.final_answer = redacted_answer

        logger.bind(
            conversation_id=state.conversation_id,
            safety_passed=review.passed,
            redacted=review.redacted,
        ).info("Safety guard completed.")

        return AgentResult(
            agent="safety",
            output=review.model_dump_json(),
            metadata={"passed": review.passed, "redacted": review.redacted, "issues": review.issues},
        )

    def _redact(self, text: str) -> tuple[str, list[str]]:
        """Replace recognizable secrets with [REDACTED_SECRET] and return detected issues."""
        issues: list[str] = []
        redacted = text
        for pattern in self.SECRET_PATTERNS:
            if pattern.search(redacted):
                issues.append("Potential secret or token detected.")
                redacted = pattern.sub("[REDACTED_SECRET]", redacted)
        return redacted, issues
