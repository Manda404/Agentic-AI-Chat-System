"""
Agent de routage des outils.

Le `ToolRouterAgent` lit le plan produit par `LLMPlannerAgent` et le transforme
en route concrète pour les transitions conditionnelles LangGraph. Il évite que
le graphe appelle des outils inutiles et fournit un fallback sûr si l'intention
du planner est inconnue.
"""

from app.logger import logger
from app.models.chat_models import AgentResult
from app.state import GraphState


class ToolRouterAgent:
    """
    Convertit une intention métier en route exécutable par le graphe.

    Exemples :
    - `greeting` -> nœud de salutation ;
    - `document_qa` -> recherche documentaire ;
    - `requires_rag=True` -> pipeline RAG complet ;
    - intention inconnue -> fallback vers une réponse directe.
    """

    ROUTES = {
        "greeting": "greeting",
        "direct_answer": "direct_answer",
        "summarization": "direct_answer",
        "analysis": "direct_answer",
        "correction": "direct_answer",
        "planning": "direct_answer",
        "calculation": "calculation",
        "document_list": "document_list",
        "document_qa": "document_qa",
        "unknown": "fallback",
    }

    async def run(self, state: GraphState) -> AgentResult:
        """Lit `state.planner_decision`, choisit `state.route`, puis trace ce choix."""
        decision = state.planner_decision
        intent = decision.intent if decision else state.intent or "unknown"
        route = self.ROUTES.get(intent, "fallback")

        # Les flags du planner sont prioritaires sur le mapping simple d'intention.
        if decision and decision.requires_rag:
            route = "rag"
        elif decision and decision.requires_retrieval:
            route = "document_qa"

        # La route devient la valeur utilisée par les conditional edges du workflow.
        state.route = route
        state.intent = intent
        state.metadata["tool_route"] = route

        logger.bind(
            conversation_id=state.conversation_id,
            intent=intent,
            route=route,
            tools=state.tools,
        ).info("Tool router completed.")

        return AgentResult(
            agent="tool_router",
            output=f"Route selected from plan: {route}",
            metadata={"intent": intent, "route": route, "tools": state.tools},
        )
