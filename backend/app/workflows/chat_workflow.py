"""
Workflow LangGraph du chat multi-agent.

`ChatWorkflow.run()` reste le point d'entrée appelé par `/api/v1/chat` :
il gère le cache Redis et l'historique, puis délègue l'orchestration à un
`StateGraph` composé de nœuds agents explicites.
"""

import hashlib
import time
import uuid
from typing import Awaitable, Callable, Optional

from langgraph.graph import END, START, StateGraph

from app.agents.context_compression_agent import ContextCompressionAgent
from app.agents.corrective_rag_agent import CorrectiveRAGAgent
from app.agents.citation_validator_agent import CitationValidatorAgent
from app.agents.final_answer_agent import FinalAnswerAgent
from app.agents.hybrid_retriever_agent import HybridRetrieverAgent
from app.agents.llm_critic_agent import LLMCriticAgent
from app.agents.llm_planner_agent import LLMPlannerAgent
from app.agents.memory_agent import MemoryAgent
from app.agents.rag_agent import RAGAgent
from app.agents.reranker_agent import RerankerAgent
from app.agents.safety_guard_agent import SafetyGuardAgent
from app.agents.search_agent import SearchAgent
from app.agents.summary_agent import SummaryAgent
from app.agents.tool_router_agent import ToolRouterAgent
from app.agents.tool_executor_agent import ToolExecutorAgent
from app.config.settings import settings
from app.logger import clear_log_context, logger, set_log_context, update_log_context
from app.memory.redis_memory import RedisMemoryService
from app.models.chat_models import AgentResult, ChatRequest, ChatResponse, PlannerDecision
from app.services.embedding_service import HuggingFaceEmbeddingService
from app.services.llm_service import LLMService
from app.services.mongo_vector_store import MongoVectorStore
from app.services.search_service import SearchService
from app.state import GraphState
from app.state.graph_state import GraphStateDict
from app.tools import CalculatorTool, CitationValidatorTool, DocumentListTool

if settings.langfuse_enabled:
    try:
        from langfuse import observe
    except ImportError:
        def observe(*args, **kwargs):
            def decorator(func):
                return func
            return decorator if args and callable(args[0]) else decorator
else:
    def observe(*args, **kwargs):
        def decorator(func):
            return func
        return decorator if args and callable(args[0]) else decorator


NodeHandler = Callable[[GraphState], Awaitable[AgentResult]]


class ChatWorkflow:
    """Orchestre le chat via un graphe LangGraph compilé une seule fois."""

    def __init__(
        self,
        memory_service: Optional[RedisMemoryService] = None,
        cache_service: Optional[RedisMemoryService] = None,
        search_service: Optional[SearchService] = None,
        llm_service: Optional[LLMService] = None,
        embedding_service: Optional[HuggingFaceEmbeddingService] = None,
    ) -> None:
        self.memory_service = memory_service or RedisMemoryService(
            settings.redis_url, settings.redis_ttl_seconds
        )
        self.cache_service = cache_service or self.memory_service
        self.search_service = search_service or SearchService()
        self.llm_service = llm_service or LLMService()
        self.embedding_service = embedding_service or HuggingFaceEmbeddingService()

        self.memory_agent = MemoryAgent(self.memory_service)
        self.planner_agent = LLMPlannerAgent(self.llm_service)
        self.tool_router_agent = ToolRouterAgent()
        self.tool_executor_agent = ToolExecutorAgent(
            calculator=CalculatorTool(),
            document_list=DocumentListTool(self.search_service),
        )
        self.summary_agent = SummaryAgent(self.llm_service)
        self.search_agent = SearchAgent(self.search_service)
        self.hybrid_retriever_agent = HybridRetrieverAgent(
            vector_store=MongoVectorStore(self.search_service, self.embedding_service)
        )
        self.reranker_agent = RerankerAgent(
            max_results=settings.max_rag_documents,
            embedding_service=self.embedding_service if settings.semantic_reranker_enabled else None,
        )
        self.corrective_rag_agent = CorrectiveRAGAgent(
            self.llm_service,
            min_relevance=settings.corrective_rag_min_relevance,
        )
        self.context_compression_agent = ContextCompressionAgent(
            self.llm_service,
            max_chars=settings.max_rag_context_chars,
        )
        self.rag_agent = RAGAgent(self.llm_service)
        self.citation_validator_agent = CitationValidatorAgent(CitationValidatorTool())
        self.critic_agent = LLMCriticAgent(self.llm_service)
        self.safety_guard_agent = SafetyGuardAgent(self.llm_service)
        self.final_answer_agent = FinalAnswerAgent()

        self.graph = self._build_graph()

    @observe(name="chat_workflow")
    async def run(self, request: ChatRequest, user_id: Optional[str] = None) -> ChatResponse:
        """Traite un message : cache -> LangGraph -> mémoire/cache -> réponse API."""
        conversation_id = request.conversation_id or str(uuid.uuid4())
        set_log_context(thread_id=conversation_id, agent_type="workflow")
        owner_scope = self._cache_owner_scope(user_id)

        try:
            stored_context = await self.memory_service.get_messages(conversation_id, owner_id=user_id)
            if len(request.message) > settings.max_user_message_chars:
                answer = f"Message is too long. Maximum length is {settings.max_user_message_chars} characters."
                return ChatResponse(
                    conversation_id=conversation_id,
                    route="safety",
                    answer=answer,
                    agents_used=["safety"],
                    agent_results=[
                        AgentResult(
                            agent="safety",
                            output=answer,
                            metadata={"reason": "message_too_long"},
                        )
                    ],
                    cached=False,
                    context_messages=len(stored_context),
                    safety_feedback=answer,
                    safety_passed=False,
                    trace_id=conversation_id,
                )
            document_version = await self.cache_service.get_value("documents:version") or "0"
            cache_key = f"chat:{owner_scope}:{conversation_id}:docs:{document_version}:{request.message.strip().lower()}"
            cached_answer = await self.cache_service.get_value(cache_key)

            logger.bind(
                conversation_id=conversation_id,
                user_id=user_id or "anonymous",
                history_count=len(request.history),
                message_preview=request.message[:120],
            ).info("Chat workflow started.")

            if cached_answer:
                logger.bind(conversation_id=conversation_id).info("Cache hit for chat response.")
                return ChatResponse(
                    conversation_id=conversation_id,
                    route="cache",
                    answer=cached_answer,
                    agents_used=["cache"],
                    agent_results=[
                        AgentResult(
                            agent="cache",
                            output=cached_answer,
                            metadata={"cache_hit": True},
                        )
                    ],
                    cached=True,
                    context_messages=len(stored_context),
                    critic_passed=True,
                    safety_passed=True,
                    evaluation={"cache": {"hit": True, "documents_version": document_version}},
                    trace_id=conversation_id,
                )

            await self.memory_service.append_message(conversation_id, "user", request.message, owner_id=user_id)

            initial_state = GraphState(
                conversation_id=conversation_id,
                user_message=request.message,
                history=request.history,
                transaction_id=conversation_id,
                metadata={"user_id": user_id} if user_id else {},
                evaluation={"cache": {"hit": False, "documents_version": document_version}},
            )
            graph_config = (
                {"configurable": {"thread_id": conversation_id}}
                if settings.langgraph_checkpoint_enabled
                else None
            )
            final_payload = await self.graph.ainvoke(initial_state.to_dict(), config=graph_config)
            state = GraphState.from_mapping(final_payload)

            answer = state.final_answer or "I could not produce an answer for this request."
            await self.memory_service.append_message(conversation_id, "assistant", answer, owner_id=user_id)
            await self.cache_service.set_value(cache_key, answer)

            logger.bind(
                conversation_id=conversation_id,
                route=state.route,
                agents_used=state.agents_used,
                final_answer_length=len(answer),
            ).info("Chat workflow completed.")

            return ChatResponse(
                conversation_id=conversation_id,
                route=state.route or "unknown",
                answer=answer,
                agents_used=state.agents_used,
                agent_results=state.agent_results,
                tool_results=state.tool_results,
                cached=False,
                context_messages=len(await self.memory_service.get_messages(conversation_id, owner_id=user_id)),
                plan=state.plan,
                critic_feedback=state.critic_feedback,
                critic_passed=state.critic_passed,
                critic_score=state.critic_score,
                retrieval_metrics=state.retrieval_metrics,
                safety_feedback=state.safety_feedback,
                safety_passed=state.safety_passed,
                evaluation=state.evaluation,
                trace_id=state.transaction_id or conversation_id,
            )
        finally:
            clear_log_context()

    def _build_graph(self):
        graph = StateGraph(GraphStateDict)

        graph.add_node("memory", self._agent_node("MemoryAgent", self.memory_agent.run))
        graph.add_node("planner", self._agent_node("LLMPlannerAgent", self.planner_agent.run))
        graph.add_node("tool_router", self._agent_node("ToolRouterAgent", self.tool_router_agent.run))
        graph.add_node("tool_executor", self._agent_node("ToolExecutorAgent", self.tool_executor_agent.run))
        graph.add_node("greeting", self._greeting_node)
        graph.add_node("search", self._agent_node("SearchAgent", self.search_agent.run, swallow_errors=True))
        graph.add_node("hybrid_retriever", self._agent_node("HybridRetrieverAgent", self.hybrid_retriever_agent.run, swallow_errors=True))
        graph.add_node("reranker", self._agent_node("RerankerAgent", self.reranker_agent.run, swallow_errors=True))
        graph.add_node("corrective_rag", self._agent_node("CorrectiveRAGAgent", self.corrective_rag_agent.run, swallow_errors=True))
        graph.add_node("prepare_retrieval_retry", self._prepare_retrieval_retry_node)
        graph.add_node("context_compression", self._agent_node("ContextCompressionAgent", self.context_compression_agent.run, swallow_errors=True))
        graph.add_node("summary", self._agent_node("SummaryAgent", self.summary_agent.run, swallow_errors=True))
        graph.add_node("rag", self._agent_node("RAGAgent", self.rag_agent.run, swallow_errors=True))
        graph.add_node("citation_validator", self._agent_node("CitationValidatorAgent", self.citation_validator_agent.run))
        graph.add_node("critic", self._agent_node("CriticAgent", self.critic_agent.run))
        graph.add_node("skip_critic", self._skip_critic_node)
        graph.add_node("safety", self._agent_node("SafetyGuardAgent", self.safety_guard_agent.run))
        graph.add_node("skip_safety", self._skip_safety_node)
        graph.add_node("prepare_rag_retry", self._prepare_retry_node("rag"))
        graph.add_node("prepare_summary_retry", self._prepare_retry_node("summary"))
        graph.add_node("final_answer", self._agent_node("FinalAnswerAgent", self.final_answer_agent.run))

        graph.add_edge(START, "memory")
        graph.add_edge("memory", "planner")
        graph.add_edge("planner", "tool_router")
        graph.add_conditional_edges(
            "tool_router",
            self._route_after_tool_router,
            {
                "greeting": "greeting",
                "direct_answer": "summary",
                "document_qa": "search",
                "rag": "search",
                "calculation": "tool_executor",
                "document_list": "tool_executor",
                "fallback": "summary",
            },
        )
        graph.add_conditional_edges(
            "tool_executor",
            self._route_to_critic,
            {
                "critic": "critic",
                "skip_critic": "skip_critic",
            },
        )
        graph.add_edge("search", "hybrid_retriever")
        graph.add_edge("hybrid_retriever", "reranker")
        graph.add_conditional_edges(
            "reranker",
            self._route_after_reranker,
            {
                "corrective_rag": "corrective_rag",
                "context_compression": "context_compression",
            },
        )
        graph.add_conditional_edges(
            "corrective_rag",
            self._route_after_corrective_rag,
            {
                "search": "prepare_retrieval_retry",
                "context_compression": "context_compression",
                "critic": "critic",
            },
        )
        graph.add_edge("prepare_retrieval_retry", "search")
        graph.add_conditional_edges(
            "context_compression",
            self._route_after_retrieval,
            {
                "rag": "rag",
                "critic": "critic",
            },
        )
        graph.add_conditional_edges(
            "greeting",
            self._route_to_critic,
            {
                "critic": "critic",
                "skip_critic": "skip_critic",
            },
        )
        graph.add_conditional_edges(
            "summary",
            self._route_to_critic,
            {
                "critic": "critic",
                "skip_critic": "skip_critic",
            },
        )
        graph.add_edge("rag", "citation_validator")
        graph.add_conditional_edges(
            "citation_validator",
            self._route_to_critic,
            {
                "critic": "critic",
                "skip_critic": "skip_critic",
            },
        )
        graph.add_conditional_edges(
            "critic",
            self._route_after_critic,
            {
                "safety": "safety",
                "skip_safety": "skip_safety",
                "retry_rag": "prepare_rag_retry",
                "retry_summary": "prepare_summary_retry",
            },
        )
        graph.add_edge("prepare_rag_retry", "rag")
        graph.add_edge("prepare_summary_retry", "summary")
        graph.add_edge("safety", "final_answer")
        graph.add_conditional_edges(
            "skip_critic",
            self._route_to_safety,
            {
                "safety": "safety",
                "skip_safety": "skip_safety",
            },
        )
        graph.add_edge("skip_safety", "final_answer")
        graph.add_edge("final_answer", END)
        return self._compile_graph(graph)

    def _cache_owner_scope(self, user_id: Optional[str]) -> str:
        """Scope court du cache pour éviter les collisions entre utilisateurs."""
        if not user_id:
            return "shared"
        return hashlib.sha256(user_id.strip().lower().encode("utf-8")).hexdigest()[:16]

    def _agent_node(
        self,
        node_name: str,
        handler: NodeHandler,
        swallow_errors: bool = False,
    ) -> Callable[[GraphStateDict], Awaitable[GraphStateDict]]:
        async def node(payload: GraphStateDict) -> GraphStateDict:
            state = GraphState.from_mapping(payload)
            update_log_context(agent_type=node_name, route=state.route or "-")
            started_at = time.perf_counter()
            logger.bind(
                conversation_id=state.conversation_id,
                node=node_name,
                message_preview=state.user_message[:120],
            ).info("LangGraph node started.")
            try:
                result = await handler(state)
                state.record_result(result)
            except Exception as exc:
                logger.bind(
                    conversation_id=state.conversation_id,
                    node=node_name,
                    elapsed_ms=round((time.perf_counter() - started_at) * 1000, 2),
                ).exception("LangGraph node failed.")
                state.error = str(exc)
                if not swallow_errors:
                    raise
                fallback = self._fallback_result(node_name, exc, state)
                state.record_result(fallback)
            elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
            state.evaluation.setdefault("latency_ms", {})[node_name] = elapsed_ms
            logger.bind(
                conversation_id=state.conversation_id,
                node=node_name,
                elapsed_ms=elapsed_ms,
                output_preview=(state.agent_results[-1].output[:160] if state.agent_results else ""),
            ).info("LangGraph node completed.")
            return state.to_dict()

        return node

    async def _prepare_retrieval_retry_node(self, payload: GraphStateDict) -> GraphStateDict:
        state = GraphState.from_mapping(payload)
        state.retrieval_correction_attempted = True
        state.search_results = []
        state.reranked_results = []
        state.compressed_context = None
        state.search_output = None
        state.rag_output = None
        state.draft_answer = None
        state.record_result(
            AgentResult(
                agent="retrieval_retry",
                output="Corrective RAG requested a second retrieval pass with a rewritten query.",
                metadata={"retrieval_query": state.metadata.get("retrieval_query")},
            )
        )
        state.evaluation.setdefault("latency_ms", {})["prepare_retrieval_retry"] = 0.0
        return state.to_dict()

    def _prepare_retry_node(self, target: str) -> Callable[[GraphStateDict], Awaitable[GraphStateDict]]:
        async def node(payload: GraphStateDict) -> GraphStateDict:
            state = GraphState.from_mapping(payload)
            state.correction_attempted = True
            state.record_result(
                AgentResult(
                    agent="critic_retry",
                    output=f"One bounded correction attempt requested for {target}.",
                    metadata={"target": target},
                )
            )
            logger.bind(
                conversation_id=state.conversation_id,
                target=target,
            ).info("Critic retry prepared.")
            state.evaluation.setdefault("latency_ms", {})[f"prepare_{target}_retry"] = 0.0
            return state.to_dict()

        return node

    async def _greeting_node(self, payload: GraphStateDict) -> GraphStateDict:
        state = GraphState.from_mapping(payload)
        update_log_context(agent_type="Greeting", route=state.route or "-")
        started_at = time.perf_counter()
        greeting_reply = (
            "Hello, bonjour. How can I help you?\n\n"
            "You can ask me to search the indexed knowledge base, generate a grounded answer, "
            "summarize a topic, or review a draft."
        )
        state.final_answer = greeting_reply
        state.draft_answer = greeting_reply
        state.record_result(
            AgentResult(
                agent="greeting",
                output=greeting_reply,
                metadata={"route": "greeting"},
            )
        )
        elapsed_ms = round((time.perf_counter() - started_at) * 1000, 2)
        state.evaluation.setdefault("latency_ms", {})["Greeting"] = elapsed_ms
        logger.bind(
            conversation_id=state.conversation_id,
            elapsed_ms=elapsed_ms,
            output_preview=greeting_reply[:160],
        ).info("LangGraph node completed.")
        return state.to_dict()

    async def _skip_critic_node(self, payload: GraphStateDict) -> GraphStateDict:
        state = GraphState.from_mapping(payload)
        state.critic_passed = True
        state.critic_score = None
        state.critic_feedback = "Critic skipped by quality policy."
        state.evaluation["critic"] = {"skipped": True, "reason": "route_policy"}
        state.record_result(
            AgentResult(
                agent="critic_skipped",
                output=state.critic_feedback,
                metadata={"skipped": True},
            )
        )
        return state.to_dict()

    async def _skip_safety_node(self, payload: GraphStateDict) -> GraphStateDict:
        state = GraphState.from_mapping(payload)
        state.safety_passed = True
        state.safety_feedback = "Safety skipped by runtime policy."
        state.evaluation["safety"] = {"skipped": True, "reason": "runtime_policy"}
        state.record_result(
            AgentResult(
                agent="safety_skipped",
                output=state.safety_feedback,
                metadata={"skipped": True},
            )
        )
        return state.to_dict()

    def _compile_graph(self, graph: StateGraph):
        if not settings.langgraph_checkpoint_enabled:
            return graph.compile()
        try:
            if settings.langgraph_checkpoint_backend == "memory":
                from langgraph.checkpoint.memory import MemorySaver

                logger.info("LangGraph memory checkpointing enabled.")
                return graph.compile(checkpointer=MemorySaver())
        except Exception as exc:
            logger.bind(reason=str(exc)).warning(
                "LangGraph checkpointing could not be enabled; compiling without checkpointer."
            )
        return graph.compile()

    def _route_after_tool_router(self, payload: GraphStateDict) -> str:
        route = payload.get("route") or "fallback"
        if route == "greeting":
            return "greeting"
        if route in {"direct_answer", "analysis", "correction", "planning"}:
            return "direct_answer"
        if route in {"document_qa", "rag"}:
            return "rag"
        if route in {"calculation", "document_list"}:
            return route
        return "fallback"

    def _route_after_retrieval(self, payload: GraphStateDict) -> str:
        route = payload.get("route") or "rag"
        decision = payload.get("planner_decision") or {}
        requires_rag = decision.get("requires_rag", True) if isinstance(decision, dict) else True
        if route == "document_qa" and not requires_rag:
            return "critic"
        return "rag"

    def _route_after_reranker(self, payload: GraphStateDict) -> str:
        if settings.corrective_rag_enabled:
            return "corrective_rag"
        return "context_compression"

    def _route_after_corrective_rag(self, payload: GraphStateDict) -> str:
        corrective = payload.get("retrieval_metrics", {}).get("corrective_rag", {})
        if corrective.get("decision") == "rewrite":
            return "search"
        if corrective.get("decision") in {"insufficient_evidence", "fallback"}:
            return "critic"
        return "context_compression"

    def _route_to_critic(self, payload: GraphStateDict) -> str:
        if self._requires_critic(payload):
            return "critic"
        return "skip_critic"

    def _route_after_critic(self, payload: GraphStateDict) -> str:
        if payload.get("critic_passed", False):
            return self._route_to_safety(payload)
        if payload.get("correction_attempted", False):
            return self._route_to_safety(payload)

        route = payload.get("route") or "rag"
        if route in {"rag", "parallel"} and payload.get("search_results"):
            return "retry_rag"
        if route in {"direct_answer", "summary", "simple_llm", "planning", "correction"}:
            return "retry_summary"
        return self._route_to_safety(payload)

    def _route_to_safety(self, payload: GraphStateDict) -> str:
        if settings.safety_enabled:
            return "safety"
        return "skip_safety"

    def _requires_critic(self, payload: GraphStateDict) -> bool:
        if not settings.critic_enabled:
            return False
        route = str(payload.get("route") or "")
        enabled_routes = {item.strip() for item in settings.critic_routes.split(",") if item.strip()}
        route_enabled = "*" in enabled_routes or route in enabled_routes
        if not route_enabled:
            return False
        if route in {"rag", "document_qa"} or bool(payload.get("search_results")):
            return True
        decision = payload.get("planner_decision")
        if isinstance(decision, dict) and decision.get("requires_critic") is False:
            return False
        if isinstance(decision, PlannerDecision) and not decision.requires_critic:
            return False
        return True

    def _fallback_result(self, node_name: str, exc: Exception, state: GraphState) -> AgentResult:
        agent_name = node_name.replace("Agent", "").lower()
        output = f"{node_name} is temporarily unavailable. Error: {exc}"
        if node_name == "SearchAgent":
            state.search_output = output
            state.search_results = []
        elif node_name == "SummaryAgent":
            state.summary_output = output
        elif node_name == "RAGAgent":
            state.rag_output = state.search_output or output
        elif node_name == "HybridRetrieverAgent":
            state.retrieval_metrics["hybrid_error"] = str(exc)
        elif node_name == "RerankerAgent":
            state.reranked_results = state.search_results
            state.retrieval_metrics["reranker_error"] = str(exc)
        elif node_name == "CorrectiveRAGAgent":
            state.retrieval_metrics["corrective_rag_error"] = str(exc)
        elif node_name == "ContextCompressionAgent":
            state.compressed_context = state.search_output
            state.retrieval_metrics["compression_error"] = str(exc)
        return AgentResult(
            agent=agent_name,
            output=output,
            metadata={"fallback": True, "reason": type(exc).__name__},
        )
