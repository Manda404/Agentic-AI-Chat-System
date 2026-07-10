"""
Agent de finalisation de réponse.

Dernier nœud du graphe LangGraph, cet agent transforme les sorties candidates
des agents précédents en `final_answer`. Il ne génère pas de nouveau contenu :
il choisit la meilleure réponse disponible et ajoute, si nécessaire, les notes
du critic ou du safety guard.
"""

from app.logger import logger
from app.models.chat_models import AgentResult
from app.state import GraphState


class FinalAnswerAgent:
    """Choisit la meilleure sortie disponible et prépare la réponse API finale."""

    async def run(self, state: GraphState) -> AgentResult:
        """
        Remplit `state.final_answer` avec une réponse compatible frontend.

        Priorité des sources :
        1. réponse déjà redigée/finalisée ;
        2. brouillon courant ;
        3. sortie RAG ;
        4. sortie summary ;
        5. sortie search ;
        6. fallback générique.
        """
        # Choisir la meilleure réponse candidate produite par les agents précédents.
        answer = (
            state.final_answer
            or state.draft_answer
            or state.rag_output
            or state.summary_output
            or state.search_output
            or "I could not produce an answer for this request."
        )

        # Le safety guard peut bloquer/rediger : on conserve sa note pour transparence.
        if not state.safety_passed and state.safety_feedback:
            answer = f"{answer}\n\nSafety note: {state.safety_feedback}"

        # Si le critic n'a pas validé la réponse, la note reste visible côté utilisateur/debug.
        if state.critic_feedback and not state.critic_passed and state.critic_feedback != "OK":
            answer = f"{answer}\n\nValidation note: {state.critic_feedback}"

        state.final_answer = answer.strip()

        logger.bind(
            conversation_id=state.conversation_id,
            answer_length=len(state.final_answer),
            critic_passed=state.critic_passed,
            safety_passed=state.safety_passed,
        ).info("Final answer agent completed.")

        return AgentResult(
            agent="final_answer",
            output=state.final_answer,
            metadata={"critic_passed": state.critic_passed, "safety_passed": state.safety_passed},
        )
