"""
Planner déterministe historique.

Ce module est conservé comme composant simple et pédagogique. Le workflow
principal utilise désormais `LLMPlannerAgent`, mais ce planner reste utile pour
des tests, des démonstrations ou un fallback très lisible.
"""

from app.logger import logger
from app.models.chat_models import AgentResult
from app.state import GraphState


class PlannerAgent:
    """Construit un plan court et déterministe pour guider le graphe LangGraph."""

    async def run(self, state: GraphState) -> AgentResult:
        """Déduit les étapes à partir de `state.route` et les stocke dans `state.plan`."""
        route = state.route or "rag"
        # Mapping volontairement simple : une route connue -> une liste d'étapes attendues.
        plans = {
            "greeting": ["greeting", "critic_review", "final_answer"],
            "search": ["search_documents", "critic_review", "final_answer"],
            "summary": ["generate_direct_answer", "critic_review", "final_answer"],
            "simple_llm": ["generate_direct_answer", "critic_review", "final_answer"],
            "rag": ["search_documents", "generate_grounded_answer", "critic_review", "final_answer"],
            "parallel": ["search_documents", "generate_grounded_answer", "critic_review", "final_answer"],
            "planning": ["generate_direct_answer", "critic_review", "final_answer"],
            "correction": ["generate_direct_answer", "critic_review", "final_answer"],
        }
        state.plan = plans.get(route, plans["rag"])

        # AgentResult garde le plan visible dans le cockpit frontend.
        output = {"steps": state.plan}
        logger.bind(route=route, plan=state.plan).info("Planner agent completed.")
        return AgentResult(agent="planner", output=str(output), metadata={"steps": state.plan})
