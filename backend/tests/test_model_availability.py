"""Availability records real provider calls, not configuration or answer quality."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.llm_service import LLMService
from app.routers.health_router import health


class ModelAvailabilityTests(unittest.IsolatedAsyncioTestCase):
    def service(self):
        with patch.object(LLMService, '_initialize_client'):
            service = LLMService()
        service.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=AsyncMock())))
        return service

    async def test_health_reports_last_call_and_recovery_without_new_requests(self):
        llm = self.service()
        def probe():
            return health(SimpleNamespace(using_redis=True), SimpleNamespace(available=True), SimpleNamespace(llm=llm))
        self.assertEqual(probe()['llm_status'], 'unverified')
        self.assertIsNone(probe()['llm_checked_at'])
        llm.client.chat.completions.create.assert_not_awaited()
        llm.client.chat.completions.create.side_effect = RuntimeError('provider unavailable')
        with self.assertRaises(RuntimeError):
            await llm.generate('test', model='test')
        self.assertEqual(probe()['llm_status'], 'offline')
        self.assertIsNotNone(probe()['llm_checked_at'])
        llm.client.chat.completions.create.side_effect = None
        llm.client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='invalid action, but the provider responded'))])
        await llm.generate('test', model='test')
        self.assertEqual(probe()['llm_status'], 'online')
        self.assertIsNone(probe()['llm_failure_reason'])
        self.assertEqual(llm.client.chat.completions.create.await_count, 2)

    async def test_missing_client_is_offline(self):
        llm = self.service()
        llm.client = None
        with self.assertRaises(RuntimeError):
            await llm.generate('test')
        self.assertEqual(llm.last_call_status, 'offline')

    async def test_startup_probe_is_bounded_and_handles_failure(self):
        llm = self.service()
        llm.client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='OK'))])
        await llm.check_availability()
        self.assertEqual(llm.last_call_status, 'online')
        self.assertEqual(llm.client.chat.completions.create.call_args.kwargs['max_tokens'], 1)
        llm.client.chat.completions.create.side_effect = TimeoutError()
        await llm.check_availability()
        self.assertEqual(llm.last_call_status, 'offline')
        self.assertEqual(llm.last_call_reason, 'llm_unavailable')

    async def test_exhausted_credits_are_reported_without_provider_body(self):
        import httpx
        from openai import APIStatusError
        from app.agents.final_answer_agent import FinalAnswerAgent
        from app.state import GraphState
        llm = self.service()
        llm.client.chat.completions.create.side_effect = APIStatusError(
            'billing error', response=httpx.Response(402, request=httpx.Request('POST', 'https://provider.invalid')),
            body={'error': 'You have depleted your monthly included credits.', 'private': 'provider-debug-data'})
        with self.assertRaises(APIStatusError):
            await llm.generate('test', model='test')
        result = health(SimpleNamespace(using_redis=True), SimpleNamespace(available=True), SimpleNamespace(llm=llm))
        self.assertEqual(result['llm_failure_reason'], 'llm_credits_exhausted')
        self.assertNotIn('provider-debug-data', str(result))
        state = GraphState(conversation_id='test', user_message='test', metadata={'answer_failure': result['llm_failure_reason']})
        await FinalAnswerAgent().run(state)
        self.assertIn('monthly credits are exhausted', state.final_answer)
        self.assertIn('Add credits', state.final_answer)
        llm.client.chat.completions.create.side_effect = None
        llm.client.chat.completions.create.return_value = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='OK'))])
        await llm.generate('test', model='test')
        self.assertIsNone(llm.last_call_reason)
