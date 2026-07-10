"""
Critic déterministe de secours.

Le projet utilise maintenant `LLMCriticAgent` comme critic principal, mais ce
module reste important : il fournit une validation locale, rapide et bornée si
le LLM critic est indisponible ou renvoie une sortie invalide.
"""

from app.logger import logger
from app.models.chat_models import AgentResult
from app.state import GraphState


class CriticAgent:
    """Relit la réponse candidate avec des règles simples et bornées."""

    async def run(self, state: GraphState) -> AgentResult:
        """
        Vérifie présence de réponse, ancrage documentaire et adéquation minimale.

        Ce critic ne prétend pas mesurer la vérité complète : il détecte les
        erreurs évidentes qui doivent empêcher une finalisation silencieuse.
        """
        candidate = state.rag_output or state.summary_output or state.search_output or state.final_answer or ""
        feedback = []

        # Règles minimales : réponse existante, documents présents, sources visibles, longueur utile.
        if not candidate.strip():
            feedback.append("No draft answer was produced.")
        if state.route in {"rag", "parallel"} and not state.search_results:
            feedback.append("The route expects document grounding, but no document was found.")
        if state.search_results and "Sources:" not in candidate and state.route in {"rag", "parallel"}:
            feedback.append("The grounded answer should keep visible sources.")
        if len(candidate.strip()) < 12:
            feedback.append("The draft answer is too short to be useful.")

        state.critic_passed = not feedback
        state.critic_feedback = "OK" if state.critic_passed else " ".join(feedback)

        logger.bind(
            conversation_id=state.conversation_id,
            critic_passed=state.critic_passed,
            feedback=state.critic_feedback,
        ).info("Critic agent completed.")

        return AgentResult(
            agent="critic",
            output=state.critic_feedback,
            metadata={"passed": state.critic_passed},
        )
