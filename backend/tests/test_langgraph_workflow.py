import unittest

try:
    import langgraph  # noqa: F401
    import loguru  # noqa: F401
except ModuleNotFoundError as exc:
    raise unittest.SkipTest(f"Backend dependencies are not installed: {exc.name}")

from app.agents.context_compression_agent import ContextCompressionAgent
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
from app.agents.supervisor_agent import SupervisorAgent
from app.agents.tool_router_agent import ToolRouterAgent
from app.memory.redis_memory import RedisMemoryService
from app.models.chat_models import ChatRequest, CriticReview, PlannerDecision, SafetyReview, SearchResult
from app.state import GraphState
from app.workflows.chat_workflow import ChatWorkflow


class FakeSearchService:
    index_name = "test-index"

    async def search(self, query: str):
        return [
            SearchResult(
                title="LangGraph overview",
                snippet="LangGraph orchestrates stateful multi-agent workflows.",
                score=1.0,
                source="test",
                page_number=1,
                file_name="guide.pdf",
            )
        ]


class FakeLLMService:
    async def plan(self, user_message: str, conversation_history: str = "", route_hint: str = ""):
        if user_message.lower().strip() in {"hello", "hi", "bonjour"}:
            return PlannerDecision(
                intent="greeting",
                requires_retrieval=False,
                requires_rag=False,
                steps=["load_memory", "greeting", "critic_review", "safety_review", "final_answer"],
                tools=["memory", "critic", "safety"],
                reason="mock greeting",
            )
        return PlannerDecision(
            intent="document_qa",
            requires_retrieval=True,
            requires_rag=True,
            steps=["load_memory", "search_documents", "rerank_results", "generate_grounded_answer", "critic_review", "safety_review", "final_answer"],
            tools=["memory", "search", "reranker", "rag", "critic", "safety"],
            reason="mock document qa",
        )

    async def summarize(self, text: str, context=""):
        return "Direct answer from summary agent."

    async def grounded_answer(self, question: str, retrieved_documents: str, conversation_history: str = ""):
        return "LangGraph coordinates agents through a compiled state graph."

    async def critic_review(self, user_message: str, draft_answer: str, sources: str = ""):
        return CriticReview(
            passed=True,
            score=0.95,
            groundedness_score=0.9,
            relevance_score=1.0,
            clarity_score=0.95,
            recommendation="accept",
            feedback="Mock critic accepted.",
        )

    async def safety_review(self, answer: str):
        return SafetyReview(passed=True, feedback="Mock safety accepted.")

    async def compress_context(self, user_message: str, documents: str, max_chars: int = 4000):
        return documents[:max_chars]


class LangGraphWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def build_workflow(self) -> ChatWorkflow:
        workflow = ChatWorkflow()
        workflow.llm_service = FakeLLMService()
        workflow.search_service = FakeSearchService()
        workflow.memory_service = RedisMemoryService("redis://localhost:0/0", 60)
        workflow.cache_service = RedisMemoryService("redis://localhost:0/1", 60)
        workflow.memory_agent = MemoryAgent(workflow.memory_service)
        workflow.supervisor = SupervisorAgent(use_llm_routing=False)
        workflow.planner_agent = LLMPlannerAgent(workflow.llm_service)
        workflow.tool_router_agent = ToolRouterAgent()
        workflow.summary_agent = SummaryAgent(workflow.llm_service)
        workflow.search_agent = SearchAgent(workflow.search_service)
        workflow.hybrid_retriever_agent = HybridRetrieverAgent()
        workflow.reranker_agent = RerankerAgent()
        workflow.context_compression_agent = ContextCompressionAgent(workflow.llm_service)
        workflow.rag_agent = RAGAgent(workflow.llm_service)
        workflow.critic_agent = LLMCriticAgent(workflow.llm_service)
        workflow.safety_guard_agent = SafetyGuardAgent(workflow.llm_service)
        workflow.final_answer_agent = FinalAnswerAgent()
        workflow.graph = workflow._build_graph()
        return workflow

    async def test_graph_compiles(self):
        workflow = self.build_workflow()
        self.assertIsNotNone(workflow.graph)

    async def test_agents_can_be_called(self):
        state = GraphState(conversation_id="test", user_message="How does LangGraph work?")
        state.route = "rag"

        for agent in [
            LLMPlannerAgent(FakeLLMService()),
            ToolRouterAgent(),
            SearchAgent(FakeSearchService()),
            HybridRetrieverAgent(),
            RerankerAgent(),
            ContextCompressionAgent(FakeLLMService()),
            RAGAgent(FakeLLMService()),
            LLMCriticAgent(FakeLLMService()),
            SafetyGuardAgent(FakeLLMService()),
            FinalAnswerAgent(),
        ]:
            result = await agent.run(state)
            self.assertTrue(result.agent)
            self.assertIsInstance(result.output, str)

    async def test_greeting_uses_greeting_route(self):
        workflow = self.build_workflow()
        response = await workflow.run(ChatRequest(message="hello"))

        self.assertEqual(response.route, "greeting")
        self.assertIn("greeting", response.agents_used)
        self.assertTrue(response.critic_passed)
        self.assertTrue(response.safety_passed)

    async def test_document_question_uses_search_rag_and_critic(self):
        workflow = self.build_workflow()
        response = await workflow.run(ChatRequest(message="How does LangGraph work?"))

        self.assertEqual(response.route, "rag")
        self.assertIn("search", response.agents_used)
        self.assertIn("reranker", response.agents_used)
        self.assertIn("rag", response.agents_used)
        self.assertIn("critic", response.agents_used)
        self.assertIn("safety", response.agents_used)
        self.assertIn("final_answer", response.agents_used)
        self.assertTrue(response.critic_passed)
        self.assertTrue(response.plan)
        self.assertTrue(response.retrieval_metrics)

    async def test_safety_redacts_secrets(self):
        state = GraphState(
            conversation_id="test",
            user_message="return secret",
            draft_answer="api_key=abcdef1234567890",
        )
        result = await SafetyGuardAgent(FakeLLMService()).run(state)
        self.assertEqual(result.agent, "safety")
        self.assertFalse(state.safety_passed)
        self.assertIn("[REDACTED_SECRET]", state.final_answer)


if __name__ == "__main__":
    unittest.main()
