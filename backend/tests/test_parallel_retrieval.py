import asyncio
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock

from app.agents.hybrid_retriever_agent import HybridRetrieverAgent
from app.agents.search_agent import SearchAgent
from app.state import GraphState
from app.models.chat_models import SearchResult


def doc(key):
    return SearchResult(document_id=key, title=key, snippet='Useful evidence', source='test', score=1)


class ParallelRetrievalTests(unittest.IsolatedAsyncioTestCase):
    def state(self):
        return GraphState(conversation_id='test', user_message='Original question',
                          metadata={'user_id': 'alice', 'retrieval_query': 'Focused query'})

    async def test_both_branches_start_before_either_completes(self):
        text_started, vector_started = asyncio.Event(), asyncio.Event()
        calls = []
        async def text(query, owner_id):
            calls.append(('text', query, owner_id))
            text_started.set()
            await vector_started.wait()
            return [doc('shared'), doc('text')]
        async def vector(query, limit, owner_id):
            calls.append(('vector', query, owner_id))
            vector_started.set()
            await text_started.wait()
            return [doc('shared'), doc('vector')]
        hybrid = HybridRetrieverAgent(SimpleNamespace(similarity_search=vector))
        search = SearchAgent(SimpleNamespace(search=text, index_name='test'))
        state = self.state()
        async with asyncio.timeout(1):
            _, _, fulltext = await hybrid.run_parallel(state, search)
        self.assertEqual(set(calls), {('text', 'Focused query', 'alice'), ('vector', 'Focused query', 'alice')})
        expected = hybrid._merge([doc('shared'), doc('text')], [doc('shared'), doc('vector')])
        self.assertEqual(state.search_results, expected)
        self.assertEqual(len(fulltext), 2)
        self.assertEqual(state.retrieval_metrics['retrieval_execution'], 'parallel')
        self.assertEqual(state.retrieval_metrics['retrieval_status'], 'ok')
        self.assertIn('parallel_search', state.evaluation['component_latency_ms'])

    async def test_partial_failures_and_total_failure_are_distinct(self):
        for text_fails, vector_fails, expected in [(True, False, 'degraded'), (False, True, 'degraded'), (True, True, 'unavailable'), (False, False, 'ok')]:
            with self.subTest(text_fails=text_fails, vector_fails=vector_fails):
                search = SearchAgent(SimpleNamespace(index_name='test', search=AsyncMock(
                    side_effect=RuntimeError('secret-text') if text_fails else None, return_value=[doc('text')])))
                hybrid = HybridRetrieverAgent(SimpleNamespace(similarity_search=AsyncMock(
                    side_effect=RuntimeError('secret-vector') if vector_fails else None, return_value=[doc('vector')])))
                state = self.state()
                await hybrid.run_parallel(state, search)
                self.assertEqual(state.retrieval_metrics['retrieval_status'], expected)
                self.assertEqual({d.document_id for d in state.search_results},
                                 (set() if text_fails else {'text'}) | (set() if vector_fails else {'vector'}))
                self.assertNotIn('secret', str(state.retrieval_metrics))

    async def test_empty_results_are_not_a_provider_failure_and_clear_old_errors(self):
        search = SearchAgent(SimpleNamespace(index_name='test', search=AsyncMock(return_value=[])))
        hybrid = HybridRetrieverAgent(SimpleNamespace(similarity_search=AsyncMock(return_value=[])))
        state = self.state()
        state.retrieval_metrics.update(search_error='old', vector_error='old')
        await hybrid.run_parallel(state, search)
        self.assertEqual(state.retrieval_metrics['retrieval_status'], 'ok')
        self.assertNotIn('vector_error', state.retrieval_metrics)
        self.assertNotIn('search_error', state.retrieval_metrics)
        self.assertEqual(state.search_results, [])

    async def test_cancellation_stops_both_async_branches(self):
        started = [asyncio.Event(), asyncio.Event()]
        stopped = [asyncio.Event(), asyncio.Event()]
        async def block(index):
            started[index].set()
            try:
                await asyncio.Event().wait()
            finally:
                stopped[index].set()
        search = SearchAgent(SimpleNamespace(index_name='test', search=lambda *a, **k: block(0)))
        hybrid = HybridRetrieverAgent(SimpleNamespace(similarity_search=lambda *a, **k: block(1)))
        task = asyncio.create_task(hybrid.run_parallel(self.state(), search))
        try:
            async with asyncio.timeout(1):
                await asyncio.gather(*(event.wait() for event in started))
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                await asyncio.gather(*(event.wait() for event in stopped))
        finally:
            task.cancel()

    async def test_concurrent_requests_do_not_share_results_or_owner(self):
        async def text(query, owner_id):
            await asyncio.sleep(0)
            return [doc(owner_id + '-text')]
        async def vector(query, owner_id, limit):
            await asyncio.sleep(0)
            return [doc(owner_id + '-vector')]
        search = SearchAgent(SimpleNamespace(index_name='test', search=text))
        hybrid = HybridRetrieverAgent(SimpleNamespace(similarity_search=vector))
        states = [self.state(), self.state()]
        states[1].metadata['user_id'] = 'bob'
        await asyncio.gather(*(hybrid.run_parallel(state, search) for state in states))
        for owner, state in zip(('alice', 'bob'), states):
            self.assertEqual({item.document_id for item in state.search_results}, {owner + '-text', owner + '-vector'})
