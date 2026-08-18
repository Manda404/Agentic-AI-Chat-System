"""
Agent de critique LLM avec fallback déterministe.

Après une réponse provisoire (`draft_answer`, `rag_output` ou `summary_output`),
ce module vérifie si la réponse est pertinente, claire et suffisamment ancrée
dans les sources. Il utilise le LLM quand c'est possible, mais garde le
`CriticAgent` déterministe comme filet de sécurité.
"""

from app.agents.critic_agent import CriticAgent
from app.logger import logger
from app.models.chat_models import AgentResult, CriticReview
from app.services.llm_service import LLMService
from app.state import GraphState


class LLMCriticAgent:
    """Évalue une réponse provisoire avec un LLM, puis fallback sur `CriticAgent`."""

    def __init__(self, llm_service: LLMService):
        """Prépare le critic LLM et son critic de secours sans appel réseau."""
        self.llm_service = llm_service
        self.fallback_critic = CriticAgent()

    async def run(self, state: GraphState) -> AgentResult:
        """
        Produit une revue qualité structurée et l'écrit dans `GraphState`.

        La réponse candidate peut provenir du RAG, du summary, de la recherche
        ou d'un fallback. Le résultat est exposé dans `state.evaluation["critic"]`
        et dans les champs `critic_passed`, `critic_feedback`, `critic_score`.
        """
        draft = state.draft_answer or state.rag_output or state.summary_output or state.search_output or state.final_answer or ""
        sources = state.compressed_context or state.search_output or ""
        try:
            # Chemin nominal : revue LLM validée par le modèle Pydantic CriticReview.
            review = await self.llm_service.critic_review(
                user_message=state.user_message,
                draft_answer=draft,
                sources=sources,
            )
            source = "llm"
        except Exception as exc:
            logger.bind(reason=str(exc)).warning("LLM critic failed; using deterministic fallback.")
            # Fallback : conserver une validation minimale même sans LLM critic.
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
        if state.route == "rag" and citation_validation and not citation_validation.get("passed", False):
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

        # Le workflow lit ces champs pour décider retry ou finalisation.
        state.critic_passed = review.passed
        state.critic_feedback = review.feedback
        state.critic_score = review.score
        state.evaluation["critic"] = review.model_dump()

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
