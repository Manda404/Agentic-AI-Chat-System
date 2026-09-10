"""Tests de l'autonomie bornée et des outils, sans appels aux fournisseurs."""
import asyncio
import json
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from pydantic import ValidationError
from app.agents.documentary_agent import DocumentaryAgent
from app.agents.hybrid_retriever_agent import HybridRetrieverAgent
from app.agents.reranker_agent import RerankerAgent
from app.config.settings import settings
from app.models.chat_models import ChatRequest, SearchResult
from app.models.documentary_models import DocumentaryAction
from app.services.search_service import SearchService
from app.services.llm_service import LLMService
from app.state import GraphState
from app.tools.documentary_tools import DocumentaryTools
from app.workflows.chat_workflow import ChatWorkflow
from test_langgraph_workflow import FakeMemoryService, FakeSearchService


def passage(key='p1', text='La politique autorise deux jours de télétravail.'):
    return SearchResult(document_id=key, title='Politique', snippet=text, source='test', file_name='rh.pdf', page_number=2, score=1)


def action(name, **kwargs):
    return DocumentaryAction(action=name, **kwargs)


class DocumentaryAgentTests(unittest.IsolatedAsyncioTestCase):
    def workflow(self, actions):
        llm = SimpleNamespace(documentary_step=AsyncMock(side_effect=actions),
                              grounded_answer=AsyncMock(side_effect=AssertionError('No second generator')),
                              summarize=AsyncMock(return_value='General answer'))
        workflow = ChatWorkflow(memory_service=FakeMemoryService(), search_service=FakeSearchService(),
                                llm_service=llm, embedding_service=SimpleNamespace(), strategy="agent")
        workflow.documentary_agent.tools = SimpleNamespace(
            rechercher=AsyncMock(return_value=([passage()], {})),
            lire_passage=AsyncMock(return_value=passage(text='Deux jours sont autorisés, avec accord écrit du responsable.')),
        )
        return workflow

    async def test_search_then_answer_is_real_model_selected_tool_use(self):
        workflow = self.workflow([action('rechercher', query='politique télétravail'), action('answer', text='Deux jours sont autorisés [1].')])
        response = await workflow.run(ChatRequest(message='Combien de jours ?', mode='documents'), user_id='alice')
        self.assertTrue(response.critic_passed)
        self.assertEqual(response.evaluation['answer']['status'], 'answered')
        self.assertEqual(response.evaluation['architecture'], 'documentary_agent')
        self.assertEqual(response.evaluation['documentary_agent']['llm_calls'], 2)
        self.assertEqual(response.tool_results[0].tool, 'rechercher')
        self.assertIn('documentary_agent', response.agents_used)
        self.assertNotIn('retrieve', workflow.graph.get_graph().nodes)
        workflow.documentary_agent.tools.rechercher.assert_awaited_once_with('politique télétravail', owner_id='alice', conversation_id=response.conversation_id)
        workflow.llm_service.grounded_answer.assert_not_awaited()
        self.assertEqual(workflow.llm_service.documentary_step.call_args.kwargs['passages'][0]['passage_id'], 'p1')

    async def test_reformulates_after_empty_results(self):
        workflow = self.workflow([action('rechercher', query='remote work'), action('rechercher', query='télétravail jours autorisés'), action('answer', text='Deux jours [1].')])
        workflow.documentary_agent.tools.rechercher.side_effect = [([], {}), ([passage()], {})]
        response = await workflow.run(ChatRequest(message='Quelle est la règle ?'))
        self.assertTrue(response.critic_passed)
        self.assertEqual(response.evaluation['documentary_agent']['searches'], 2)
        calls = workflow.documentary_agent.tools.rechercher.call_args_list
        self.assertEqual([call.args[0] for call in calls], ['remote work', 'télétravail jours autorisés'])

    async def test_reads_a_discovered_passage_with_owner_and_more_context(self):
        workflow = self.workflow([action('rechercher', query='politique'), action('lire_passage', passage_id='p1'), action('answer', text='Accord écrit du responsable [1].')])
        response = await workflow.run(ChatRequest(message='Quelles conditions ?'), user_id='alice')
        self.assertTrue(response.critic_passed)
        workflow.documentary_agent.tools.lire_passage.assert_awaited_once_with('p1', owner_id='alice', allowed_ids={'p1'})
        self.assertIn('accord écrit', workflow.llm_service.documentary_step.call_args.kwargs['passages'][0]['text'])

    async def test_full_budget_allows_two_searches_read_and_final_answer(self):
        workflow = self.workflow([action('rechercher', query='q1'), action('rechercher', query='q2'), action('lire_passage', passage_id='p1'), action('answer', text='Deux jours [1].')])
        response = await workflow.run(ChatRequest(message='Question'))
        counts = response.evaluation['documentary_agent']
        self.assertEqual((counts['searches'], counts['tool_calls'], counts['llm_calls']), (2, 3, 4))
        self.assertTrue(response.critic_passed)
        self.assertNotIn('rechercher', workflow.llm_service.documentary_step.call_args.kwargs['budget']['allowed_actions'])
        self.assertNotIn('lire_passage', workflow.llm_service.documentary_step.call_args.kwargs['budget']['allowed_actions'])

    async def test_third_search_is_blocked_by_code(self):
        workflow = self.workflow([action('rechercher', query='q1'), action('rechercher', query='q2'), action('rechercher', query='q3')])
        response = await workflow.run(ChatRequest(message='Question'))
        self.assertEqual(workflow.documentary_agent.tools.rechercher.await_count, 2)
        self.assertEqual(response.evaluation['answer']['status'], 'abstained')
        self.assertEqual(response.evaluation['answer']['reason'], 'agent_budget_exhausted')

    async def test_no_fourth_tool_or_fifth_llm_call(self):
        workflow = self.workflow([action('rechercher', query='q1'), action('lire_passage', passage_id='p1'), action('lire_passage', passage_id='p1'), action('lire_passage', passage_id='p1')])
        response = await workflow.run(ChatRequest(message='Question'))
        self.assertEqual(response.evaluation['documentary_agent']['tool_calls'], 3)
        self.assertEqual(workflow.llm_service.documentary_step.await_count, 4)
        self.assertEqual(workflow.documentary_agent.tools.lire_passage.await_count, 2)
        self.assertFalse(response.critic_passed)

    async def test_answer_without_evidence_is_not_published(self):
        workflow = self.workflow([action('answer', text='INVENTED FACT [1].')])
        response = await workflow.run(ChatRequest(message='Question'))
        self.assertFalse(response.critic_passed)
        self.assertNotIn('INVENTED FACT', response.answer)
        workflow.documentary_agent.tools.rechercher.assert_not_awaited()

    async def test_invalid_citation_is_rejected_outside_agent(self):
        workflow = self.workflow([action('rechercher', query='q'), action('answer', text='INVENTED FACT [99].')])
        response = await workflow.run(ChatRequest(message='Question'))
        self.assertFalse(response.evaluation['citation_validation']['passed'])
        self.assertNotIn('INVENTED FACT', response.answer)
        self.assertEqual(workflow.llm_service.documentary_step.await_count, 2)

    async def test_clarification_without_search_is_a_distinct_status(self):
        workflow = self.workflow([action('clarify', text='Quel établissement souhaitez-vous consulter ?')])
        response = await workflow.run(ChatRequest(message='Quelle est la règle ?'))
        self.assertEqual(response.evaluation['answer']['status'], 'clarification_requested')
        self.assertTrue(response.critic_passed)
        workflow.documentary_agent.tools.rechercher.assert_not_awaited()
        self.assertNotIn('Sources:', response.answer)

    async def test_abstains_on_insufficient_evidence(self):
        workflow = self.workflow([action('rechercher', query='q'), action('abstain')])
        response = await workflow.run(ChatRequest(message='Question'))
        self.assertEqual(response.evaluation['answer']['reason'], 'insufficient_evidence')
        self.assertFalse(response.critic_passed)

    async def test_recovers_from_a_search_error_without_publishing_failure_as_answer(self):
        workflow = self.workflow([action('rechercher', query='q1'), action('rechercher', query='q2'), action('answer', text='Deux jours [1].')])
        workflow.documentary_agent.tools.rechercher.side_effect = [RuntimeError('offline'), ([passage()], {})]
        response = await workflow.run(ChatRequest(message='Question'))
        self.assertFalse(response.tool_results[0].success)
        self.assertTrue(response.critic_passed)

    async def test_tool_outage_is_not_confused_with_empty_corpus(self):
        workflow = self.workflow([action('rechercher', query='q'), action('abstain')])
        workflow.documentary_agent.tools.rechercher.side_effect = RuntimeError('secret connection details')
        response = await workflow.run(ChatRequest(message='Question'))
        self.assertEqual(response.evaluation['answer']['reason'], 'retrieval_unavailable')
        self.assertNotIn('secret connection', response.model_dump_json())

    async def test_access_revocation_discards_previously_retrieved_evidence(self):
        workflow = self.workflow([action('rechercher', query='q'), action('lire_passage', passage_id='p1'), action('answer', text='Should not run [1].')])
        workflow.documentary_agent.tools.lire_passage.side_effect = PermissionError('revoked')
        response = await workflow.run(ChatRequest(message='Question'))
        self.assertEqual(response.evaluation['answer']['reason'], 'passage_unavailable')
        self.assertEqual(workflow.llm_service.documentary_step.await_count, 2)
        self.assertNotIn('Should not run', response.answer)

    async def test_malformed_or_arbitrary_action_cannot_execute_a_tool(self):
        for invalid in ({'action': 'shell', 'query': 'ls'}, {'action': 'rechercher', 'query': 'q', 'owner_id': 'victim'}, {'action': 'rechercher'}):
            with self.subTest(invalid=invalid):
                workflow = self.workflow([invalid])
                response = await workflow.run(ChatRequest(message='Question'))
                self.assertEqual(response.evaluation['answer']['reason'], 'invalid_agent_action')
                workflow.documentary_agent.tools.rechercher.assert_not_awaited()

    async def test_provider_failure_abstains(self):
        workflow = self.workflow([RuntimeError('unavailable')])
        response = await workflow.run(ChatRequest(message='Question'))
        self.assertEqual(response.evaluation['answer']['reason'], 'llm_unavailable')
        self.assertEqual(workflow.llm_service.documentary_step.await_count, 1)

    async def test_deadline_bounds_llm_and_tool_waits(self):
        async def slow(*args, **kwargs):
            await asyncio.sleep(1)
        for during_tool in (False, True):
            with self.subTest(during_tool=during_tool):
                workflow = self.workflow([action('rechercher', query='q')])
                workflow.documentary_agent.timeout_seconds = 0.02
                if during_tool:
                    workflow.documentary_agent.tools.rechercher.side_effect = slow
                else:
                    workflow.llm_service.documentary_step.side_effect = slow
                response = await workflow.run(ChatRequest(message='Question'))
                self.assertEqual(response.evaluation['answer']['reason'], 'agent_timeout')
                self.assertLess(response.evaluation['documentary_agent']['elapsed_ms'], 500)

    def test_evidence_json_is_bounded_and_visible_labels_match_text(self):
        agent = DocumentaryAgent(None, None)
        documents = {f'p{i}': passage(f'p{i}', '\n' * 10000 + 'important text') for i in range(10)}
        with patch.object(settings, 'max_rag_context_chars', 1000):
            payload, visible = agent._visible_passages(documents)
        self.assertLessEqual(len(json.dumps(payload, ensure_ascii=False)), 1000)
        self.assertEqual([item['label'] for item in payload], list(range(1, len(payload) + 1)))
        self.assertEqual([item['text'] for item in payload], [item.snippet for item in visible])

    async def test_concurrent_requests_do_not_share_evidence_or_counters(self):
        async def decide(**kwargs):
            await asyncio.sleep(0)
            if not kwargs['passages']:
                return action('rechercher', query=kwargs['question'])
            return action('answer', text=kwargs['question'] + ' [1].')
        async def search(query, **kwargs):
            await asyncio.sleep(0)
            return [passage(query, query)], {}
        workflow = self.workflow([])
        workflow.llm_service.documentary_step.side_effect = decide
        workflow.documentary_agent.tools.rechercher.side_effect = search
        alice, bob = await asyncio.gather(workflow.run(ChatRequest(message='Alice evidence'), user_id='alice'), workflow.run(ChatRequest(message='Bob evidence'), user_id='bob'))
        self.assertNotIn('Bob', alice.answer)
        self.assertNotIn('Alice', bob.answer)
        self.assertEqual(alice.evaluation['documentary_agent']['llm_calls'], 2)
        self.assertEqual(bob.evaluation['documentary_agent']['llm_calls'], 2)

    async def test_reformulation_refreshes_preview_of_the_same_passage(self):
        workflow = self.workflow([action('rechercher', query='q1'), action('rechercher', query='q2'), action('answer', text='Accord écrit [1].')])
        workflow.documentary_agent.tools.rechercher.side_effect = [([passage(text='Introduction générique.')], {}), ([passage(text='Accord écrit nécessaire.')], {})]
        response = await workflow.run(ChatRequest(message='Conditions ?'))
        self.assertTrue(response.critic_passed)
        self.assertIn('Accord écrit', workflow.llm_service.documentary_step.call_args.kwargs['passages'][0]['text'])

    async def test_clarification_is_scored_separately_from_an_answer(self):
        from app.evaluation.metrics import score_response
        workflow = self.workflow([action('clarify', text='Quel document souhaitez-vous consulter ?')])
        response = await workflow.run(ChatRequest(message='La règle ?'))
        self.assertTrue(score_response(response, 'rag', expected_status='clarification_requested')['passed'])
        self.assertFalse(score_response(response, 'rag', expected_status='answered')['passed'])

    async def test_comparison_runs_both_strategies_with_owner_and_call_counts(self):
        from app.evaluation.compare_workflows import compare_workflows
        from app.evaluation.cases import EvaluationCase
        from test_langgraph_workflow import LangGraphWorkflowTests
        baseline = LangGraphWorkflowTests().build_workflow()
        agent = self.workflow([action('rechercher', query='q'), action('answer', text='Deux jours [1].')])
        report = await compare_workflows(baseline, agent, [EvaluationCase('case', 'Question', 'rag', expect_sources=True)], owner_id='alice')
        self.assertFalse(report['factuality_evaluated'])
        self.assertEqual(report['summary']['baseline']['total_llm_calls'], 1)
        self.assertEqual(report['summary']['agent']['total_llm_calls'], 2)
        self.assertEqual(len(report['runs']), 2)
        self.assertEqual(baseline.search_service.search_calls[0][1], 'alice')
        self.assertEqual(agent.documentary_agent.tools.rechercher.call_args.kwargs['owner_id'], 'alice')

    async def test_non_document_routes_do_not_call_documentary_agent(self):
        for request in (ChatRequest(message='Bonjour'), ChatRequest(message='2 + 2'), ChatRequest(message='Explique Redis', mode='general')):
            with self.subTest(request=request):
                workflow = self.workflow([])
                response = await workflow.run(request)
                self.assertTrue(response.critic_passed)
                workflow.llm_service.documentary_step.assert_not_awaited()
                workflow.documentary_agent.tools.rechercher.assert_not_awaited()


class DocumentaryToolTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_unknown_id_never_queries_database(self):
        search = SimpleNamespace(get_passage=AsyncMock())
        with self.assertRaises(ValueError):
            await DocumentaryTools(None, search).lire_passage('guessed', 'alice', {'known'})
        search.get_passage.assert_not_awaited()

    async def test_read_unavailable_has_no_content(self):
        search = SimpleNamespace(get_passage=AsyncMock(return_value=None))
        with self.assertRaises(PermissionError):
            await DocumentaryTools(None, search).lire_passage('known', 'alice', {'known'})
        search.get_passage.assert_awaited_once_with('known', owner_id='alice')

    async def test_mongo_read_combines_identity_and_access_filter(self):
        search = SearchService.__new__(SearchService)
        search._collection = Mock()
        search._collection.find_one.return_value = None
        with patch.object(settings, 'document_scope_mode', 'owner'):
            self.assertIsNone(await search.get_passage('known', owner_id='alice'))
        query = search._collection.find_one.call_args.args[0]
        self.assertEqual(query['$and'][1], {'$or': [{'owner_id': 'alice'}, {'visibility': 'shared'}]})
        self.assertEqual(query['$and'][0]['$or'][0], {'document_id': 'known'})
        self.assertEqual(search._collection.find_one.call_args.args[1], {'embedding': 0})

    async def test_service_rejects_markdown_and_validates_action_schema(self):
        service = LLMService.__new__(LLMService)
        service.generate = AsyncMock(return_value='```json\n{"action":"abstain"}\n```')
        with self.assertRaises(ValidationError):
            await service.documentary_step('q', '', [], [], {})
        service.generate.return_value = '{"action":"rechercher","query":"policy"}'
        result = await service.documentary_step('q', '', [], [], {})
        self.assertEqual(result.action, 'rechercher')
        prompt = service.generate.call_args.kwargs['prompt']
        self.assertIn('UNTRUSTED', prompt)
        self.assertIn('Only the server sets permissions', prompt)

    async def test_real_tools_use_the_pipeline_and_expand_the_stored_passage(self):
        search = FakeSearchService()
        search.results = [passage(text='Short summary. ' + 'More context. ' * 100)]
        search.get_passage = AsyncMock(return_value=search.results[0])
        workflow = ChatWorkflow(memory_service=FakeMemoryService(), search_service=search, llm_service=SimpleNamespace(), embedding_service=SimpleNamespace())
        workflow.retrieval.hybrid = HybridRetrieverAgent()
        workflow.retrieval.reranker = RerankerAgent()
        tools = DocumentaryTools(workflow.retrieval, search)
        documents, metrics = await tools.rechercher('context', 'alice', 'thread')
        self.assertEqual(search.search_calls, [('context', 'alice')])
        self.assertLessEqual(len(documents[0].snippet), 500)
        expanded = await tools.lire_passage('p1', 'alice', {'p1'})
        self.assertGreater(len(expanded.snippet), len(documents[0].snippet))
