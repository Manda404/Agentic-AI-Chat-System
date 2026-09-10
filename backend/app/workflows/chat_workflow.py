"""Bounded chat graph with a collaborative documentary team and direct routes. Redis holds conversation history; LangGraph controls execution and correction budgets."""
import time
import uuid
from typing import Optional

from langgraph.graph import END, START, StateGraph

from app.agents.citation_validator_agent import CitationValidatorAgent
from app.agents.documentary_agent import DocumentaryAgent
from app.agents.documentary_team import DocumentaryTeam
from app.tools.documentary_tools import DocumentaryTools
from app.agents.critic_agent import CriticAgent
from app.agents.final_answer_agent import FinalAnswerAgent
from app.agents.rag_agent import RAGAgent
from app.agents.safety_guard_agent import SafetyGuardAgent
from app.agents.summary_agent import SummaryAgent
from app.agents.tool_executor_agent import ToolExecutorAgent
from app.config.settings import settings
from app.logger import clear_log_context, logger, set_log_context
from app.memory.redis_memory import RedisMemoryService
from app.models.chat_models import AgentResult, ChatRequest, ChatResponse
from app.services.embedding_service import HuggingFaceEmbeddingService
from app.services.llm_service import LLMService
from app.services.retrieval_pipeline import RetrievalPipeline
from app.services.search_service import SearchService
from app.state import GraphState
from app.state.graph_state import GraphStateDict
from app.tools import CalculatorTool, CitationValidatorTool, DocumentListTool
from app.workflows.routing import route_request


class ChatWorkflow:
    """A bounded documentary team with two reference strategies for evaluation."""

    def __init__(self, memory_service=None, search_service=None, llm_service=None, embedding_service=None, strategy="multi_agent"):
        if strategy not in {"multi_agent", "agent", "baseline"}:
            raise ValueError("Unknown documentary strategy.")
        self.strategy = strategy
        self.memory_service = memory_service or RedisMemoryService(settings.redis_url, settings.redis_ttl_seconds)
        self.search_service = search_service or SearchService()
        self.llm_service = llm_service or LLMService()
        self.embedding_service = embedding_service or HuggingFaceEmbeddingService()
        self.retrieval = RetrievalPipeline(self.search_service, self.embedding_service)
        self.documentary_agent = DocumentaryAgent(self.llm_service, DocumentaryTools(self.retrieval, self.search_service))
        self.documentary_team = DocumentaryTeam(self.documentary_agent, self.llm_service)
        self.rag_agent = RAGAgent(self.llm_service)
        self.summary_agent = SummaryAgent(self.llm_service)
        self.tool_executor = ToolExecutorAgent(CalculatorTool(), DocumentListTool(self.search_service))
        self.citation_validator = CitationValidatorAgent(CitationValidatorTool())
        self.validator = CriticAgent()
        self.safety_guard = SafetyGuardAgent(self.llm_service)
        self.finalizer = FinalAnswerAgent()
        self.graph = self._build_graph()

    def _build_graph(self):
        graph = StateGraph(GraphStateDict)
        documentary_node = 'documentary' if self.strategy != 'baseline' else 'retrieve'
        handler = self._documentary if self.strategy != 'baseline' else self._retrieve
        for name, node_handler in (('route', self._route), (documentary_node, handler),
                                   ('answer', self._answer), ('validate', self._validate),
                                   ('finalize', self._finalize)):
            graph.add_node(name, self._node(name, node_handler))
        graph.add_edge(START, 'route')
        graph.add_conditional_edges('route', lambda state: documentary_node if state.get('route') == 'rag' else 'answer',
                                    {documentary_node: documentary_node, 'answer': 'answer'})
        graph.add_edge(documentary_node, 'validate' if self.strategy != 'baseline' else 'answer')
        graph.add_edge('answer', 'validate')
        graph.add_edge('validate', 'finalize')
        graph.add_edge('finalize', END)
        return graph.compile()

    async def _documentary(self, state):
        if self.strategy == 'multi_agent':
            await self.documentary_team.run(state)
        else:
            state.record_result(await self.documentary_agent.run(state))

    def _node(self, name, handler):
        async def node(payload):
            state = GraphState.from_mapping(payload)
            started = time.perf_counter()
            await handler(state)
            state.evaluation.setdefault('latency_ms', {})[name] = round((time.perf_counter() - started) * 1000, 2)
            return state.to_dict()
        return node

    async def _route(self, state):
        state.record_result(route_request(state))

    async def _retrieve(self, state):
        await self.retrieval.run(state)

    async def _answer(self, state):
        if state.route == 'greeting':
            state.draft_answer = 'Hello! I can search your documents and answer with sources, or perform a calculation.'
            result = AgentResult(agent='greeting', output=state.draft_answer)
        elif state.route in {'calculation', 'document_list'}:
            result = await self.tool_executor.run(state)
        else:
            agent = self.rag_agent if state.route == 'rag' else self.summary_agent
            state.evaluation['llm_calls'] = 1 if state.route != 'rag' or state.selected_documents else 0
            try:
                result = await agent.run(state)
            except Exception as exc:
                logger.bind(component='generation', error_type=type(exc).__name__).warning('Generation unavailable.')
                state.draft_answer = ''
                result = AgentResult(agent='rag' if state.route == 'rag' else 'summary', output='Generation unavailable.',
                                     metadata={'fallback': True, 'reason': 'llm_unavailable'})
            if result.metadata.get('reason') in {'no_documents', 'llm_unavailable'}:
                reason = result.metadata['reason']
                if reason == 'no_documents' and state.retrieval_metrics.get('search_error') and state.retrieval_metrics.get('vector_error'):
                    reason = 'retrieval_unavailable'
                state.metadata['answer_failure'] = reason
        state.record_result(result)

    async def _validate(self, state):
        if state.route == 'rag' and not state.metadata.get('clarification_requested'):
            state.record_result(await self.citation_validator.run(state))
        state.record_result(await self.validator.run(state))

    async def _finalize(self, state):
        state.record_result(await self.finalizer.run(state))
        # Always apply the local filter to the text that will be published.
        state.record_result(await self.safety_guard.run(state))

    async def run(self, request: ChatRequest, user_id: Optional[str] = None) -> ChatResponse:
        conversation_id = request.conversation_id or str(uuid.uuid4())
        set_log_context(thread_id=conversation_id, agent_type='workflow')
        try:
            if len(request.message) > settings.max_user_message_chars:
                return ChatResponse(conversation_id=conversation_id, route='safety',
                                    answer=f'Message too long (maximum {settings.max_user_message_chars} characters).',
                                    agents_used=['safety'], agent_results=[], safety_passed=False)
            # Load before append to avoid repeating the current message in context.
            stored = await self.memory_service.get_messages(conversation_id, owner_id=user_id)
            context = [item.model_dump() for item in request.history] if request.history else list(stored)
            state = GraphState(conversation_id=conversation_id, user_message=request.message,
                               conversation_context=context, transaction_id=conversation_id,
                               metadata={'user_id': user_id, 'request_mode': request.mode},
                               evaluation={'architecture': {'multi_agent': 'multi_agent', 'agent': 'documentary_agent', 'baseline': 'bounded_rag'}[self.strategy],
                                           'llm_calls': 0, 'llm_call_budget': {'multi_agent': DocumentaryTeam.MAX_LLM_CALLS, 'agent': 4, 'baseline': 1}[self.strategy]})
            await self.memory_service.append_message(conversation_id, 'user', request.message, owner_id=user_id)
            state = GraphState.from_mapping(await self.graph.ainvoke(state.to_dict()))
            answer = state.final_answer or 'I cannot produce a reliable answer to this request.'
            await self.memory_service.append_message(conversation_id, 'assistant', answer, owner_id=user_id)
            return ChatResponse(
                conversation_id=conversation_id, route=state.route or 'rag', answer=answer,
                agents_used=state.agents_used, agent_results=state.agent_results, tool_results=state.tool_results,
                context_messages=len(await self.memory_service.get_messages(conversation_id, owner_id=user_id)),
                plan=state.plan, critic_feedback=state.critic_feedback, critic_passed=state.critic_passed,
                critic_score=state.critic_score, retrieval_metrics=state.retrieval_metrics,
                safety_feedback=state.safety_feedback, safety_passed=state.safety_passed,
                evaluation=state.evaluation, trace_id=conversation_id,
            )
        finally:
            clear_log_context()
