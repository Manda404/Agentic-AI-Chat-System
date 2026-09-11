"""Experimental LLM planning with deterministic fallback. Convert user intent into a PlannerDecision JSON execution plan; keyword rules cover provider outages and invalid JSON. This legacy planner is not used by the current HTTP team."""

import re

from app.logger import logger
from app.models.chat_models import AgentResult, PlannerDecision
from app.services.llm_service import LLMService
from app.state import GraphState


class LLMPlannerAgent:
    """Read user_message and conversation_context to populate planner_decision, intent, plan and tools. The route field may hold a legacy routing hint."""

    def __init__(self, llm_service: LLMService):
        """Inject the LLM service used for structured planning."""
        self.llm_service = llm_service

    async def run(self, state: GraphState) -> AgentResult:
        """Format short history, request a JSON plan and store it in GraphState, or use the deterministic fallback."""
        # The planner receives compact conversation context.
        history = "\n".join(
            f"{message.get('role', 'unknown')}: {message.get('content', '')}"
            for message in state.conversation_context
        )
        try:
            # The LLM returns a Pydantic-validated PlannerDecision.
            decision = await self.llm_service.plan(
                user_message=state.user_message,
                conversation_history=history,
            )
            source = "llm"
        except Exception as exc:
            logger.bind(reason=str(exc), route=state.route).warning(
                "LLM planner failed; using deterministic fallback."
            )
            decision = self._fallback_decision(state)
            source = "fallback"

        # The plan is the source of truth for the legacy tool router.
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

    GREETING_KEYWORDS = {
        "hello", "hi", "hey", "bonjour", "salut", "coucou",
        "good morning", "good afternoon", "good evening",
    }
    SUMMARY_KEYWORDS = ["summary", "summarize", "summarise", "résume", "resume"]
    DOCUMENT_KEYWORDS = [
        "document", "documents", "indexed", "uploaded", "file", "files", "pdf",
        "fichier", "fichiers", "indexé", "indexés", "téléversé", "téléchargé",
    ]
    PLANNING_KEYWORDS = ["plan", "steps", "roadmap", "strategy", "multi-step", "étapes", "strategie"]
    CORRECTION_KEYWORDS = ["correct", "validate", "review", "critic", "fix", "corrige", "valide"]
    DOCUMENT_LIST_PHRASES = [
        "list documents", "list indexed", "what documents", "which documents",
        "liste les documents", "liste des documents", "quels documents", "documents indexés",
        "documents indexes", "fichiers indexés", "fichiers indexes",
    ]
    CALCULATION_KEYWORDS = ["calculate", "compute", "calcule", "calculer", "combien font"]

    def _fallback_decision(self, state: GraphState) -> PlannerDecision:
        """Classify the message by keywords when planning fails: greeting, direct answer, planning/correction or documentary RAG by default."""
        lowered = state.user_message.lower().strip()

        if lowered in self.GREETING_KEYWORDS:
            return PlannerDecision(
                intent="greeting",
                requires_retrieval=False,
                requires_rag=False,
                requires_critic=True,
                requires_safety=True,
                steps=["load_memory", "greeting", "critic_review", "safety_review", "final_answer"],
                tools=["memory", "critic", "safety"],
                reason="Greeting detected by fallback keyword match.",
            )
        if any(phrase in lowered for phrase in self.DOCUMENT_LIST_PHRASES):
            return PlannerDecision(
                intent="document_list",
                requires_retrieval=False,
                requires_rag=False,
                requires_critic=True,
                requires_safety=True,
                steps=["load_memory", "list_documents", "critic_review", "safety_review", "final_answer"],
                tools=["memory", "document_list", "critic", "safety"],
                reason="Indexed document inventory requested.",
            )
        has_arithmetic = bool(re.search(r"\d\s*[-+*/%^]\s*\d", lowered))
        has_numbered_calculation_request = bool(re.search(r"\d", lowered)) and any(
            keyword in lowered for keyword in self.CALCULATION_KEYWORDS
        )
        if has_arithmetic or has_numbered_calculation_request:
            return PlannerDecision(
                intent="calculation",
                requires_retrieval=False,
                requires_rag=False,
                requires_critic=True,
                requires_safety=True,
                steps=["load_memory", "calculate", "critic_review", "safety_review", "final_answer"],
                tools=["memory", "calculator", "critic", "safety"],
                reason="A deterministic calculator can answer this arithmetic request.",
            )
        is_document_request = any(word in lowered for word in self.DOCUMENT_KEYWORDS)
        if any(word in lowered for word in self.SUMMARY_KEYWORDS) and not is_document_request:
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
        if any(word in lowered for word in self.PLANNING_KEYWORDS):
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
        if any(word in lowered for word in self.CORRECTION_KEYWORDS):
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
