import json
import unittest
from unittest.mock import AsyncMock, patch
import httpx

import test_documentary_agent as helpers
from app.config.settings import settings
from app.models.chat_models import ChatRequest, SearchResult
from app.services.tavily_service import TavilyService


class TavilyTests(unittest.IsolatedAsyncioTestCase):
    async def test_request_contract_and_safe_results(self):
        response = httpx.Response(200, request=httpx.Request('POST', 'https://api.tavily.com/search'), json={'results': [
            {'title': 'Official', 'url': 'https://example.org/news', 'content': 'Public evidence'},
            {'title': 'Bad', 'url': 'javascript:alert(1)', 'content': 'bad'},
            {'title': 'Duplicate', 'url': 'https://example.org/news', 'content': 'same'}]})
        client = AsyncMock()
        client.post.return_value = response
        with patch.object(settings, 'tavily_api_key', 'test-key'), patch('app.services.tavily_service.httpx.AsyncClient') as factory:
            factory.return_value.__aenter__.return_value = client
            documents, metrics = await TavilyService().search('public query')
        self.assertEqual(len(documents), 1)
        self.assertTrue(documents[0].document_id.startswith('web:'))
        self.assertEqual(documents[0].source, 'https://example.org/news')
        self.assertEqual(client.post.call_args.kwargs['json']['query'], 'public query')
        self.assertFalse(client.post.call_args.kwargs['json']['include_answer'])
        self.assertNotIn('history', client.post.call_args.kwargs['json'])

    async def test_no_key_no_network(self):
        with patch.object(settings, 'tavily_api_key', ''), patch('app.services.tavily_service.httpx.AsyncClient') as client:
            with self.assertRaises(RuntimeError):
                await TavilyService().search('query')
            client.assert_not_called()

    def workflow(self, actions):
        w = helpers.DocumentaryAgentTests().workflow(actions)
        w.documentary_agent.tools.web_available = True
        w.documentary_agent.tools.rechercher_web = AsyncMock(return_value=([
            SearchResult(document_id='web:123', title='Public policy', snippet='Deux jours de télétravail.',
                         source='https://example.org/policy', score=0)], {'provider': 'tavily'}))
        return w

    async def test_web_sources_flow_to_validation(self):
        w = self.workflow([helpers.action('rechercher_web', query='public policy'), helpers.action('answer', text='Deux jours [1].')])
        r = await w.run(ChatRequest(message='Recherche sur internet la politique publique'))
        self.assertTrue(r.critic_passed)
        self.assertIn('https://example.org/policy', r.answer)
        self.assertEqual(r.evaluation['documentary_agent']['web_searches'], 1)
        passages = w.llm_service.documentary_step.call_args.kwargs['passages']
        self.assertEqual(passages[0]['kind'], 'web')
        self.assertNotIn('lire_passage', w.llm_service.documentary_step.call_args.kwargs['budget']['allowed_actions'])

    async def test_documents_mode_blocks_web_even_if_model_requests_it(self):
        w = self.workflow([helpers.action('rechercher_web', query='public query')])
        r = await w.run(ChatRequest(message='Recherche', mode='documents'))
        w.documentary_agent.tools.rechercher_web.assert_not_awaited()
        self.assertEqual(r.evaluation['answer']['status'], 'abstained')

    async def test_unconfigured_tool_not_offered(self):
        w = self.workflow([helpers.action('abstain')])
        w.documentary_agent.tools.web_available = False
        await w.run(ChatRequest(message='Recherche internet'))
        self.assertNotIn('rechercher_web', w.llm_service.documentary_step.call_args.kwargs['budget']['allowed_actions'])

    async def test_shared_search_budget(self):
        w = self.workflow([helpers.action('rechercher', query='internal'), helpers.action('rechercher_web', query='public'), helpers.action('rechercher_web', query='third')])
        r = await w.run(ChatRequest(message='Recherche'))
        self.assertEqual(w.documentary_agent.tools.rechercher_web.await_count, 1)
        self.assertEqual(r.evaluation['documentary_agent']['searches'], 2)
        self.assertEqual(r.evaluation['answer']['status'], 'abstained')

    async def test_provider_failure_is_sanitized(self):
        w = self.workflow([helpers.action('rechercher_web', query='public'), helpers.action('abstain')])
        w.documentary_agent.tools.rechercher_web.side_effect = RuntimeError('secret-key')
        r = await w.run(ChatRequest(message='Recherche internet'))
        self.assertEqual(r.evaluation['answer']['reason'], 'retrieval_unavailable')
        self.assertNotIn('secret-key', r.model_dump_json())

    async def test_web_evidence_reaches_all_three_agents(self):
        import test_documentary_team as team_helpers
        w = team_helpers.TeamTests().workflow([
            {'answerable': True, 'text': 'Deux jours [1].'},
            {'approved': True, 'feedback': 'Supported by public source.'}])
        web = self.workflow([]).documentary_agent.tools
        w.documentary_agent.tools = web
        w.llm_service.documentary_step.side_effect = [helpers.action('rechercher_web', query='public policy'),
                                                     helpers.action('answer', text='Deux jours [1].')]
        r = await w.run(ChatRequest(message='Recherche la règle publique sur internet'))
        self.assertTrue(r.critic_passed)
        self.assertIn('verification_agent', r.agents_used)
        for call in w.llm_service.generate.call_args_list[1:]:
            self.assertIn('web:123', call.kwargs['prompt'])
        self.assertIn('https://example.org/policy', r.answer)
