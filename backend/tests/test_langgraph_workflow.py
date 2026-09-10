"""Contrats du parcours RAG borné, sans MongoDB, Redis ou appel fournisseur."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.agents.hybrid_retriever_agent import HybridRetrieverAgent
from app.agents.reranker_agent import RerankerAgent
from app.models.chat_models import ChatRequest, ChatMessage, SearchResult
from app.workflows.chat_workflow import ChatWorkflow
from app.workflows.routing import select_route


class FakeSearchService:
    index_name = 'test-index'
    collection = None

    def __init__(self):
        self.search_calls = []
        self.results = [SearchResult(title='LangGraph overview', snippet='LangGraph orchestrates stateful workflows.',
                                     score=1, source='test', page_number=1, file_name='guide.pdf')]

    async def search(self, query, owner_id=None):
        self.search_calls.append((query, owner_id))
        return self.results

    async def list_indexed_documents(self, limit=200, owner_id=None):
        return [{'title': 'Guide', 'file_name': 'guide.pdf', 'page_number': 1, 'source': 'test'}]


class FakeMemoryService:
    def __init__(self):
        self.messages = {}
        self.values = {}

    async def get_messages(self, conversation_id, owner_id=None):
        return self.messages.get((owner_id, conversation_id), [])

    async def append_message(self, conversation_id, role, content, owner_id=None):
        self.messages.setdefault((owner_id, conversation_id), []).append({'role': role, 'content': content})


class LangGraphWorkflowTests(unittest.IsolatedAsyncioTestCase):
    def build_workflow(self):
        llm = SimpleNamespace(
            grounded_answer=AsyncMock(return_value='LangGraph orchestrates workflows [1].'),
            summarize=AsyncMock(return_value='A general answer.'),
            plan=AsyncMock(side_effect=AssertionError('No online LLM planner')),
            critic_review=AsyncMock(side_effect=AssertionError('No online LLM critic')),
            corrective_rag_review=AsyncMock(side_effect=AssertionError('No online CRAG')),
        )
        workflow = ChatWorkflow(memory_service=FakeMemoryService(), search_service=FakeSearchService(),
                                llm_service=llm, embedding_service=SimpleNamespace(), strategy="baseline")
        workflow.retrieval.hybrid = HybridRetrieverAgent()
        workflow.retrieval.reranker = RerankerAgent()
        return workflow

    def test_graph_has_five_business_steps_without_cycles(self):
        workflow = self.build_workflow()
        graph = workflow.graph.get_graph()
        self.assertEqual(set(graph.nodes) - {'__start__', '__end__'}, {'route', 'retrieve', 'answer', 'validate', 'finalize'})
        order = {'__start__': 0, 'route': 1, 'retrieve': 2, 'answer': 3, 'validate': 4, 'finalize': 5, '__end__': 6}
        self.assertTrue(all(order[edge.source] < order[edge.target] for edge in graph.edges))

    async def test_document_question_uses_one_generation_and_local_validation(self):
        workflow = self.build_workflow()
        response = await workflow.run(ChatRequest(message='Comment fonctionne LangGraph ?'), user_id='alice')
        self.assertEqual(response.route, 'rag')
        self.assertTrue(response.critic_passed)
        self.assertIsNone(response.critic_score)
        self.assertEqual(response.evaluation['critic']['source'], 'local')
        self.assertFalse(response.evaluation['critic']['factuality_evaluated'])
        self.assertEqual(response.evaluation['answer']['status'], 'answered')
        self.assertEqual(response.plan, ['route', 'retrieve', 'answer', 'validate', 'finalize'])
        self.assertEqual(workflow.llm_service.grounded_answer.await_count, 1)
        for name in ('plan', 'critic_review', 'corrective_rag_review'):
            getattr(workflow.llm_service, name).assert_not_awaited()
        self.assertEqual(workflow.search_service.search_calls, [('Comment fonctionne LangGraph ?', 'alice')])
        self.assertIn('Sources:', response.answer)
        self.assertIn('citation_validator', response.agents_used)

    async def test_greeting_without_network_generation(self):
        workflow = self.build_workflow()
        response = await workflow.run(ChatRequest(message='Bonjour !'))
        self.assertEqual(response.route, 'greeting')
        self.assertTrue(response.critic_passed)
        self.assertEqual(workflow.search_service.search_calls, [])
        workflow.llm_service.grounded_answer.assert_not_awaited()
        workflow.llm_service.summarize.assert_not_awaited()

    async def test_calculation_without_llm(self):
        workflow = self.build_workflow()
        response = await workflow.run(ChatRequest(message='Calcule 2 + 2'))
        self.assertEqual(response.route, 'calculation')
        self.assertEqual(response.answer, '2 + 2 = 4')
        self.assertTrue(response.critic_passed)
        workflow.llm_service.grounded_answer.assert_not_awaited()

    async def test_failed_calculation_is_not_success(self):
        response = await self.build_workflow().run(ChatRequest(message='Calcule 2 / 0'))
        self.assertFalse(response.critic_passed)
        self.assertIn('Calcul impossible', response.answer)
        self.assertEqual(response.evaluation['answer']['status'], 'abstained')

    async def test_inventory_uses_tool(self):
        response = await self.build_workflow().run(ChatRequest(message='Liste les documents indexés'))
        self.assertEqual(response.route, 'document_list')
        self.assertIn('guide.pdf', response.answer)
        self.assertTrue(response.critic_passed)

    async def test_invalid_citation_abstains_without_retry(self):
        workflow = self.build_workflow()
        workflow.llm_service.grounded_answer.return_value = 'UNSUPPORTED CLAIM [99].'
        response = await workflow.run(ChatRequest(message='Question documentaire'))
        self.assertFalse(response.critic_passed)
        self.assertEqual(response.evaluation['answer']['status'], 'abstained')
        self.assertNotIn('UNSUPPORTED CLAIM', response.answer)
        self.assertEqual(workflow.llm_service.grounded_answer.await_count, 1)

    async def test_missing_citations_abstains(self):
        workflow = self.build_workflow()
        workflow.llm_service.grounded_answer.return_value = 'Uncited claim.'
        response = await workflow.run(ChatRequest(message='Question documentaire'))
        self.assertFalse(response.critic_passed)
        self.assertNotIn('Uncited claim', response.answer)

    async def test_no_documents_abstains_without_generation(self):
        workflow = self.build_workflow()
        workflow.search_service.results = []
        response = await workflow.run(ChatRequest(message='Question inconnue'))
        workflow.llm_service.grounded_answer.assert_not_awaited()
        self.assertFalse(response.critic_passed)
        self.assertEqual(response.evaluation['answer']['reason'], 'no_documents')

    async def test_generation_failure_does_not_publish_raw_search(self):
        workflow = self.build_workflow()
        workflow.llm_service.grounded_answer.side_effect = RuntimeError('provider down')
        response = await workflow.run(ChatRequest(message='Question documentaire'))
        self.assertEqual(workflow.llm_service.grounded_answer.await_count, 1)
        self.assertEqual(response.evaluation['answer']['reason'], 'llm_unavailable')
        self.assertNotIn('LangGraph orchestrates', response.answer)

    async def test_general_mode_does_not_claim_document_sources(self):
        workflow = self.build_workflow()
        response = await workflow.run(ChatRequest(message='Explain Redis', mode='general'))
        self.assertEqual(response.route, 'direct_answer')
        self.assertEqual(workflow.search_service.search_calls, [])
        self.assertEqual(workflow.llm_service.summarize.await_count, 1)
        self.assertNotIn('Sources:', response.answer)

    async def test_general_failure_is_explicit(self):
        workflow = self.build_workflow()
        workflow.llm_service.summarize.side_effect = RuntimeError('provider down')
        response = await workflow.run(ChatRequest(message='hello', mode='general'))
        self.assertFalse(response.critic_passed)
        self.assertEqual(response.evaluation['answer']['reason'], 'llm_unavailable')

    async def test_current_message_is_not_duplicated_in_history(self):
        workflow = self.build_workflow()
        await workflow.run(ChatRequest(message='First question', conversation_id='same'))
        self.assertEqual(workflow.llm_service.grounded_answer.call_args.kwargs['conversation_history'], '')
        await workflow.run(ChatRequest(message='Second question', conversation_id='same'))
        context = workflow.llm_service.grounded_answer.call_args.kwargs['conversation_history']
        self.assertIn('First question', context)
        self.assertNotIn('Second question', context)

    async def test_repeated_question_reexecutes_with_current_history(self):
        workflow = self.build_workflow()
        await workflow.run(ChatRequest(message='Question', conversation_id='same'))
        response = await workflow.run(ChatRequest(message='Question', conversation_id='same', history=[ChatMessage(role='user', content='New context')]))
        self.assertFalse(response.cached)
        self.assertEqual(response.context_messages, 4)
        self.assertEqual(workflow.llm_service.grounded_answer.await_count, 2)
        self.assertIn('New context', workflow.llm_service.grounded_answer.call_args.kwargs['conversation_history'])

    async def test_history_is_scoped_by_owner(self):
        workflow = self.build_workflow()
        await workflow.run(ChatRequest(message='Alice private question', conversation_id='same'), user_id='alice')
        await workflow.run(ChatRequest(message='Bob question', conversation_id='same'), user_id='bob')
        self.assertNotIn('Alice', workflow.llm_service.grounded_answer.call_args.kwargs['conversation_history'])

    async def test_final_answer_redacts_secrets(self):
        workflow = self.build_workflow()
        workflow.llm_service.summarize.return_value = 'api_key=abcdef1234567890'
        response = await workflow.run(ChatRequest(message='q', mode='general'))
        self.assertIn('[REDACTED_SECRET]', response.answer)
        self.assertNotIn('abcdef1234567890', response.answer)
        self.assertFalse(response.safety_passed)

    def test_document_requests_are_not_misrouted_by_keywords_or_dates(self):
        for message in ('Quel est le plan de maintenance du document ?', 'Corrige la procédure selon le PDF',
                        'Summarize the indexed documents', 'Summarize my documents: what changed?', 'Que dit le rapport du 2026-09-10 ?',
                        'Le document indique 2 + 2, explique pourquoi', 'Résume Redis caching'):
            with self.subTest(message=message):
                self.assertEqual(select_route(message), 'rag')

    def test_explicit_modes_and_pasted_text(self):
        self.assertEqual(select_route('Résume ceci: un texte fourni'), 'direct_answer')
        self.assertEqual(select_route('hello', 'documents'), 'rag')
        self.assertEqual(select_route('Documents', 'general'), 'direct_answer')
        self.assertEqual(select_route('Calcule 20 % de 150'), 'calculation')

    async def test_expected_abstention_is_an_evaluation_success(self):
        from app.evaluation.metrics import score_response
        workflow = self.build_workflow()
        workflow.search_service.results = []
        response = await workflow.run(ChatRequest(message='Question inconnue'))
        self.assertTrue(score_response(response, 'rag', expected_status='abstained')['passed'])
        self.assertFalse(score_response(response, 'rag', expected_status='answered')['passed'])

    async def test_search_failure_can_still_use_vector_evidence(self):
        workflow = self.build_workflow()
        workflow.search_service.search = AsyncMock(side_effect=RuntimeError('Atlas Search unavailable'))
        vector_store = SimpleNamespace(similarity_search=AsyncMock(return_value=workflow.search_service.results))
        workflow.retrieval.hybrid = HybridRetrieverAgent(vector_store)
        response = await workflow.run(ChatRequest(message='Question documentaire'))
        self.assertTrue(response.critic_passed)
        self.assertIn('search_error', response.retrieval_metrics)
        self.assertEqual(workflow.llm_service.grounded_answer.await_count, 1)

    async def test_retrieval_outage_is_not_reported_as_an_empty_corpus(self):
        workflow = self.build_workflow()
        workflow.search_service.search = AsyncMock(side_effect=RuntimeError('text down'))
        workflow.retrieval.hybrid = HybridRetrieverAgent(SimpleNamespace(similarity_search=AsyncMock(side_effect=RuntimeError('vector down'))))
        response = await workflow.run(ChatRequest(message='Question documentaire'))
        self.assertEqual(response.evaluation['answer']['reason'], 'retrieval_unavailable')
        self.assertIn('recherche documentaire est indisponible', response.answer)
        workflow.llm_service.grounded_answer.assert_not_awaited()
