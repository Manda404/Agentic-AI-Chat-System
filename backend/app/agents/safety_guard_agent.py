"""
Agent de sécurité léger pour les réponses de chat.

Ce garde-fou intervient juste avant la finalisation. Il cherche les secrets
évidents dans la réponse candidate (clé API, token bearer, mot de passe, clé
privée) et les remplace par `[REDACTED_SECRET]`. Il peut aussi appeler un
review LLM optionnel, mais reste local par défaut pour limiter coût et latence.
"""

import re

from app.logger import logger
from app.models.chat_models import AgentResult, SafetyReview
from app.services.llm_service import LLMService
from app.state import GraphState


class SafetyGuardAgent:
    """Détecte secrets/tokens évidents et applique une revue LLM optionnelle."""

    SECRET_PATTERNS = [
        re.compile(r"(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*['\"]?([A-Za-z0-9_\-]{12,})"),
        re.compile(r"(?i)bearer\s+[A-Za-z0-9_\-.]{20,}"),
        re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    ]

    def __init__(self, llm_service: LLMService, use_llm: bool = False):
        """
        Configure le safety guard.

        Args:
            llm_service: Service utilisé si la revue LLM est activée.
            use_llm: Active une revue sécurité LLM en plus des regex locales.
        """
        self.llm_service = llm_service
        self.use_llm = use_llm

    async def run(self, state: GraphState) -> AgentResult:
        """
        Vérifie et redige la réponse candidate si nécessaire.

        Les résultats sont stockés dans :
        - `state.safety_passed`
        - `state.safety_feedback`
        - `state.evaluation["safety"]`
        """
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
                # Étape optionnelle : demander au LLM une revue sécurité plus nuancée.
                review = await self.llm_service.safety_review(redacted_answer)
            except Exception as exc:
                logger.bind(reason=str(exc)).warning("LLM safety review failed; using local safety result.")

        state.safety_passed = review.passed
        state.safety_feedback = review.feedback
        state.evaluation["safety"] = review.model_dump()
        if review.redacted:
            # Propage la version redigée vers les champs candidats pour la finalisation.
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
        """Remplace les secrets évidents par `[REDACTED_SECRET]` et retourne les problèmes détectés."""
        issues: list[str] = []
        redacted = text
        for pattern in self.SECRET_PATTERNS:
            if pattern.search(redacted):
                issues.append("Potential secret or token detected.")
                redacted = pattern.sub("[REDACTED_SECRET]", redacted)
        return redacted, issues
