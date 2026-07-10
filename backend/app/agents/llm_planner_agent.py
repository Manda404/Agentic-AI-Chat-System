"""
Agent de planification LLM du système multi-agent.

Dans ce projet, le planner est le point qui transforme une intention utilisateur
en plan d'exécution lisible par le graphe LangGraph. Il demande d'abord au LLM
de produire un JSON validé par `PlannerDecision`, puis garde un fallback
déterministe pour que le chat continue de fonctionner même sans fournisseur LLM.
"""

from app.logger import logger
from app.models.chat_models import AgentResult, PlannerDecision
from app.services.llm_service import LLMService
from app.state import GraphState


class LLMPlannerAgent:
    """
    Produit le plan qui pilote les agents suivants du workflow.

    Entrée principale :
    - `state.user_message` : demande utilisateur ;
    - `state.conversation_context` : historique court ;
    - `state.route` : indice fourni par le superviseur.

    Sorties écrites dans l'état :
    - `planner_decision` : objet Pydantic complet ;
    - `intent` : intention métier ;
    - `plan` : étapes textuelles ;
    - `tools` : outils/agents à utiliser.
    """

    def __init__(self, llm_service: LLMService):
        """Injecte le service LLM utilisé pour produire un plan JSON structuré."""
        self.llm_service = llm_service

    async def run(self, state: GraphState) -> AgentResult:
        """
        Planifie l'exécution de la requête courante.

        La méthode suit trois étapes :
        1. convertir l'historique en texte court ;
        2. demander un plan JSON au LLM ;
        3. stocker le plan dans `GraphState` ou utiliser un fallback fiable.
        """
        # Le planner reçoit un historique compact, suffisant pour comprendre le contexte.
        history = "\n".join(
            f"{message.get('role', 'unknown')}: {message.get('content', '')}"
            for message in state.conversation_context
        )
        try:
            # Chemin nominal : le LLM renvoie un PlannerDecision validé par Pydantic.
            decision = await self.llm_service.plan(
                user_message=state.user_message,
                conversation_history=history,
                route_hint=state.route or "",
            )
            source = "llm"
        except Exception as exc:
            logger.bind(reason=str(exc), route=state.route).warning(
                "LLM planner failed; using deterministic fallback."
            )
            decision = self._fallback_decision(state)
            source = "fallback"

        # Le plan devient la source de vérité pour le ToolRouterAgent.
        state.planner_decision = decision
        state.intent = decision.intent
        state.plan = decision.steps
        state.tools = decision.tools
        state.metadata["planner_reason"] = decision.reason
        state.metadata["planner_source"] = source

        logger.bind(
            conversation_id=state.conversation_id,
            intent=decision.intent,
            tools=decision.tools,
            source=source,
        ).info("LLM planner completed.")

        return AgentResult(
            agent="planner",
            output=decision.model_dump_json(),
            metadata={"source": source, "intent": decision.intent, "tools": decision.tools},
        )

    def _fallback_decision(self, state: GraphState) -> PlannerDecision:
        """
        Construit un plan déterministe quand le LLM de planning échoue.

        Ce fallback protège le workflow contre les indisponibilités LLM et les
        réponses JSON invalides. Il reste volontairement simple : salutation,
        réponse directe, planning/correction ou RAG documentaire.
        """
        route = state.route or "rag"
        lowered = state.user_message.lower().strip()

        if route == "greeting":
            return PlannerDecision(
                intent="greeting",
                requires_retrieval=False,
                requires_rag=False,
                requires_critic=True,
                requires_safety=True,
                steps=["load_memory", "greeting", "critic_review", "safety_review", "final_answer"],
                tools=["memory", "critic", "safety"],
                reason="Greeting route selected by supervisor.",
            )
        if route in {"summary", "simple_llm"} or any(word in lowered for word in ["summary", "summarize", "résume"]):
            return PlannerDecision(
                intent="summarization",
                requires_retrieval=False,
                requires_rag=False,
                requires_critic=True,
                requires_safety=True,
                steps=["load_memory", "generate_direct_answer", "critic_review", "safety_review", "final_answer"],
                tools=["memory", "summary", "critic", "safety"],
                reason="Direct LLM response is sufficient.",
            )
        if route in {"planning"} or any(word in lowered for word in ["plan", "steps", "roadmap", "étapes"]):
            return PlannerDecision(
                intent="planning",
                requires_retrieval=False,
                requires_rag=False,
                requires_critic=True,
                requires_safety=True,
                steps=["load_memory", "generate_direct_answer", "critic_review", "safety_review", "final_answer"],
                tools=["memory", "summary", "critic", "safety"],
                reason="Planning request can be handled directly.",
            )
        if route in {"correction"} or any(word in lowered for word in ["correct", "review", "corrige", "valide"]):
            return PlannerDecision(
                intent="correction",
                requires_retrieval=False,
                requires_rag=False,
                requires_critic=True,
                requires_safety=True,
                steps=["load_memory", "generate_direct_answer", "critic_review", "safety_review", "final_answer"],
                tools=["memory", "summary", "critic", "safety"],
                reason="Correction request can be handled directly.",
            )
        return PlannerDecision(
            intent="document_qa",
            requires_retrieval=True,
            requires_rag=True,
            requires_critic=True,
            requires_safety=True,
            steps=[
                "load_memory",
                "search_documents",
                "hybrid_retrieve",
                "rerank_results",
                "compress_context",
                "generate_grounded_answer",
                "critic_review",
                "safety_review",
                "final_answer",
            ],
            tools=["memory", "search", "hybrid_retriever", "reranker", "compressor", "rag", "critic", "safety"],
            reason="Default document question plan.",
        )
