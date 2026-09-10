"""Experimental LLM critic with local fallback. Evaluate the relevance, clarity and grounding of a draft, RAG output or direct answer; use CriticAgent when the provider fails."""

from app.agents.critic_agent import CriticAgent
from app.logger import logger
from app.models.chat_models import AgentResult, CriticReview
from app.services.llm_service import LLMService
from app.state import GraphState


class LLMCriticAgent:
    """Assess a candidate with an LLM and fall back to CriticAgent."""

    def __init__(self, llm_service: LLMService):
        """Configure the LLM critic and local fallback without network calls."""
        self.llm_service = llm_service
        self.fallback_critic = CriticAgent()

    async def run(self, state: GraphState) -> AgentResult:
        """Write a structured quality review to evaluation.critic and the critic_passed, critic_feedback and critic_score fields."""
        draft = state.draft_answer or state.rag_output or state.summary_output or state.search_output or state.final_answer or ""
        sources = state.compressed_context or state.search_output or ""
        try:
            # The LLM review is validated using the Pydantic CriticReview schema.
            review = await self.llm_service.critic_review(
                user_message=state.user_message,
                draft_answer=draft,
                sources=sources,
            )
            source = "llm"
        except Exception as exc:
            logger.bind(reason=str(exc)).warning("LLM critic failed; using deterministic fallback.")
            # Fallback: retain minimal validation without an LLM critic.
            fallback_result = await self.fallback_critic.run(state)
            review = CriticReview(
                passed=state.critic_passed,
                score=1.0 if state.critic_passed else 0.4,
                groundedness_score=1.0 if state.critic_passed else 0.3,
                relevance_score=1.0 if state.critic_passed else 0.5,
                clarity_score=1.0 if state.critic_passed else 0.5,
                issues=[] if state.critic_passed else [state.critic_feedback or fallback_result.output],
                recommendation="accept" if state.critic_passed else "fallback",
                feedback=state.critic_feedback or fallback_result.output,
            )
            source = "fallback"

        citation_validation = state.evaluation.get("citation_validation")
        if state.route in {"rag", "document_qa"} and citation_validation and not citation_validation.get("passed", False):
            citation_issue = "RAG citation validation failed."
            review = review.model_copy(
                update={
                    "passed": False,
                    "score": min(review.score, 0.6),
                    "groundedness_score": min(review.groundedness_score, 0.4),
                    "issues": [*review.issues, citation_issue],
                    "recommendation": "revise",
                    "feedback": f"{review.feedback} {citation_issue}".strip(),
                }
            )

        # The workflow reads these fields to choose retry or finalization.
        state.critic_passed = review.passed
        state.critic_feedback = review.feedback
        state.critic_score = review.score
        state.evaluation["critic"] = {**review.model_dump(), "source": source}

        logger.bind(
            conversation_id=state.conversation_id,
            critic_passed=review.passed,
            critic_score=review.score,
            source=source,
        ).info("LLM critic completed.")

        return AgentResult(
            agent="critic",
            output=review.model_dump_json(),
            metadata={"source": source, "passed": review.passed, "score": review.score},
        )
