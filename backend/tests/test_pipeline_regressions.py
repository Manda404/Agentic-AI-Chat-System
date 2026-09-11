"""Ingestion, retrieval and evaluation regressions without external services."""
import io
import math
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from fastapi import HTTPException, UploadFile
from app.config.settings import settings
from app.data_ingest.document_processing import text_chunks
from app.data_ingest.file_ingest import load_documents_from_directory
from app.data_ingest.pdf_ingest import load_documents_from_pdf
from app.evaluation.metrics import score_response
from app.evaluation.retrieval_metrics import precision_at_k, recall_at_k, ndcg_at_k
from app.models.auth_models import UserResponse
from app.models.chat_models import AgentResult, ChatResponse, SearchResult
from app.routers.ingest_router import _prepare_documents, _embedding_summary, ingest_uploaded_file
from app.services.embedding_service import validate_embeddings, HuggingFaceEmbeddingService
from app.services.search_service import SearchService
from app.services.mongo_vector_store import MongoVectorStore
from app.agents.hybrid_retriever_agent import HybridRetrieverAgent
from app.agents.reranker_agent import RerankerAgent
from app.agents.rag_agent import RAGAgent
from app.agents.context_compression_agent import ContextCompressionAgent
from app.agents.citation_validator_agent import CitationValidatorAgent
from app.state import GraphState
from app.tools import CitationValidatorTool
from app.workflows.chat_workflow import ChatWorkflow


def document(name='A', **kwargs):
    return SearchResult(title=name, snippet='Evidence for ' + name, score=1, source='test', **kwargs)


class PipelineRegressions(unittest.IsolatedAsyncioTestCase):
    def test_pdf_keeps_end_of_long_page(self):
        text = 'intro ' * 1000 + 'UNIQUE END EVIDENCE'
        with patch('app.data_ingest.pdf_ingest.PdfReader', return_value=SimpleNamespace(pages=[Mock(extract_text=Mock(return_value=text))])):
            docs = load_documents_from_pdf('guide.pdf')
        self.assertTrue(docs[0]['snippet'].endswith('UNIQUE END EVIDENCE'))
        chunks = text_chunks(docs[0]['snippet'], 500)
        self.assertTrue(chunks[-1].endswith('UNIQUE END EVIDENCE'))
        self.assertTrue(all(len(chunk) <= 500 for chunk in chunks))
        # Every text position must belong to at least one chunk.
        recovered = chunks[0] + ''.join(chunk[100:] for chunk in chunks[1:])
        self.assertEqual(recovered, text)

    async def test_prepare_chunks_have_unique_repeatable_ids(self):
        embedder = SimpleNamespace(embed_texts=AsyncMock(side_effect=RuntimeError('offline')))
        with patch.object(settings, 'max_ingested_snippet_chars', 10):
            docs = [{'title': 'Guide', 'snippet': 'abcdefghijklmnopqrstuv'}]
            first = await _prepare_documents(docs, embedder, 'alice', 'test')
            second = await _prepare_documents(docs, embedder, 'alice', 'test')
        self.assertEqual([x['_id'] for x in first], [x['_id'] for x in second])
        self.assertEqual(len({x['_id'] for x in first}), len(first))
        self.assertTrue(first[-1]['snippet'].endswith('uv'))
        self.assertTrue(_embedding_summary(first)['warnings'])

    async def test_empty_or_too_many_chunks_rejected_before_embedding(self):
        embedder = SimpleNamespace(embed_texts=AsyncMock())
        with self.assertRaises(HTTPException) as error:
            await _prepare_documents([], embedder, 'alice', 'empty')
        self.assertEqual(error.exception.status_code, 422)
        with patch.object(settings, 'max_ingested_snippet_chars', 5), patch.object(settings, 'max_ingest_documents', 1):
            with self.assertRaises(HTTPException) as error:
                await _prepare_documents([{'snippet': 'abcdefghijk'}], embedder, 'alice', 'large')
        self.assertEqual(error.exception.status_code, 413)
        embedder.embed_texts.assert_not_awaited()

    async def test_upload_same_pdf_has_stable_ids_despite_unique_storage_paths(self):
        ids = []
        async def index(docs):
            ids.append([d['_id'] for d in docs])
            return len(docs)
        search = SimpleNamespace(bulk_index_documents=index)
        embedding = SimpleNamespace(embed_texts=AsyncMock(side_effect=RuntimeError('offline')))
        memory = SimpleNamespace(increment_value=AsyncMock())
        user = UserResponse(email='alice@example.com', full_name='Alice')
        with TemporaryDirectory() as tmp, patch('app.routers.ingest_router.UPLOAD_DIRECTORY', Path(tmp)), patch('app.routers.ingest_router.BACKEND_ROOT', Path(tmp)), patch('app.routers.ingest_router.load_documents_from_file', side_effect=lambda *args: [{'title': 'random', 'snippet': 'PDF body', 'page_number': '1'}]):
            responses = []
            for _ in range(2):
                upload = UploadFile(filename='guide.pdf', file=io.BytesIO(b'pdf'))
                responses.append(await ingest_uploaded_file(upload, user, search, embedding))
                await upload.close()
        self.assertEqual(ids[0], ids[1])
        self.assertNotEqual(responses[0].stored_path, responses[1].stored_path)
        self.assertEqual(responses[0].embedded_count, 0)
        self.assertTrue(responses[0].warnings)

    def test_shared_ids_do_not_transfer_ownership(self):
        service = SearchService.__new__(SearchService)
        base = {'title': 'same', 'snippet': 'same', 'visibility': 'shared'}
        self.assertNotEqual(service._with_stable_id({**base, 'owner_id': 'alice'})['_id'], service._with_stable_id({**base, 'owner_id': 'bob'})['_id'])

    async def test_bulk_counts_updates_once_and_preserves_existing_vectors(self):
        service = SearchService.__new__(SearchService)
        service.index_name = 'test'
        service._collection = Mock()
        service._collection.bulk_write.return_value = SimpleNamespace(upserted_count=1, matched_count=2, modified_count=2)
        count = await service.bulk_index_documents([{'title': 'a', 'snippet': 'b'}])
        self.assertEqual(count, 3)
        operation = service._collection.bulk_write.call_args.args[0][0]
        self.assertIn('$set', operation._doc)
        self.assertNotIn('embedding', operation._doc['$set'])
        service._collection.bulk_write.side_effect = RuntimeError('partial write')
        with self.assertRaises(RuntimeError):
            await service.bulk_index_documents([{'title': 'a'}])
        service._collection.insert_many.assert_not_called()

    def test_embedding_validation(self):
        validate_embeddings([[1.0, 0.0]], 1, 2)
        for bad in ([], [[1]], [[[1], [2]]], [[math.nan, 1]], [[math.inf, 1]], [[0, 0]], [[True, 1]]):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                validate_embeddings(bad, 1, 2)

    async def test_embedding_batches_preserve_order(self):
        client = AsyncMock()
        def response(*args, **kwargs):
            vectors = [[float(text), 1.0] for text in kwargs['json']['inputs']]
            return SimpleNamespace(raise_for_status=lambda: None, json=lambda: vectors)
        client.post.side_effect = response
        context = AsyncMock()
        context.__aenter__.return_value = client
        embedder = HuggingFaceEmbeddingService()
        embedder.api_key = 'fake'
        with patch('app.services.embedding_service.httpx.AsyncClient', return_value=context), patch.object(settings, 'embedding_dimensions', 2):
            vectors = await embedder.embed_texts([str(i) for i in range(65)])
        self.assertEqual([v[0] for v in vectors], list(range(65)))
        self.assertEqual(client.post.await_count, 3)

    def test_batch_limits_before_parsing_and_reports_errors(self):
        with TemporaryDirectory() as tmp:
            Path(tmp, 'a.PDF').write_bytes(b'bad pdf')
            errors = []
            self.assertEqual(load_documents_from_directory(tmp, errors=errors), {})
            self.assertEqual(len(errors), 1)
            Path(tmp, 'b.csv').write_text('title,snippet,category\na,b,c')
            with patch.object(settings, 'max_batch_files', 1), patch('app.data_ingest.file_ingest.load_documents_from_file') as parse:
                with self.assertRaises(ValueError):
                    load_documents_from_directory(tmp)
                parse.assert_not_called()

    async def test_vector_query_prefilters_owner(self):
        search = SearchService.__new__(SearchService)
        search._collection = Mock()
        search._collection.aggregate.return_value = []
        embedding = SimpleNamespace(embed_query=AsyncMock(return_value=[1, 0]))
        with patch.object(settings, 'document_scope_mode', 'owner'):
            await MongoVectorStore(search, embedding).similarity_search('q', owner_id='alice')
        stage = search._collection.aggregate.call_args.args[0][0]['$vectorSearch']
        self.assertEqual(stage['filter'], {'$or': [{'owner_id': 'alice'}, {'visibility': 'shared'}]})

    async def test_rewrite_used_by_vector_and_reranker(self):
        state = GraphState('id', 'original', metadata={'retrieval_query': 'rewritten'})
        store = SimpleNamespace(similarity_search=AsyncMock(return_value=[document()]))
        await HybridRetrieverAgent(store).run(state)
        self.assertEqual(store.similarity_search.call_args.args[0], 'rewritten')
        embedding = SimpleNamespace(embed_query=AsyncMock(return_value=[1, 0]), embed_texts=AsyncMock(return_value=[[1, 0]]))
        await RerankerAgent(embedding_service=embedding).run(state)
        embedding.embed_query.assert_awaited_once_with('rewritten')

    async def test_vector_failure_visible_and_text_preserved(self):
        state = GraphState('id', 'q', search_results=[document()])
        store = SimpleNamespace(similarity_search=AsyncMock(side_effect=RuntimeError('index not ready')))
        await HybridRetrieverAgent(store).run(state)
        self.assertEqual(state.search_results[0].title, 'A')
        self.assertEqual('RuntimeError', state.retrieval_metrics['vector_error'])

    def test_rrf_does_not_reward_duplicates_within_one_branch(self):
        a, b = document('A', document_id='a'), document('B', document_id='b')
        merged = HybridRetrieverAgent()._merge([a, a, a], [b, a])
        self.assertAlmostEqual(merged[0].score, 1/61 + 1/62)

    def test_reranker_rejects_mismatched_dimensions(self):
        with self.assertRaises(ValueError):
            RerankerAgent()._cosine_similarity([1, 0], [1])

    async def test_filtered_empty_documents_are_not_resurrected(self):
        state = GraphState('id', 'q', search_results=[document()], retrieval_metrics={'reranked_count': 0})
        llm = SimpleNamespace(grounded_answer=AsyncMock())
        await RAGAgent(llm).run(state)
        llm.grounded_answer.assert_not_awaited()
        self.assertEqual(state.selected_documents, [])

    async def test_sources_and_validator_only_use_context_documents(self):
        docs = [document(str(i)) for i in range(6)]
        state = GraphState('id', 'q', reranked_results=docs)
        await ContextCompressionAgent(None, max_chars=35).run(state)
        self.assertLess(len(state.selected_documents), len(docs))
        llm = SimpleNamespace(grounded_answer=AsyncMock(return_value='Claim [6].'))
        result = await RAGAgent(llm).run(state)
        self.assertEqual(result.metadata['sources_count'], len(state.selected_documents))
        await CitationValidatorAgent(CitationValidatorTool()).run(state)
        self.assertFalse(state.evaluation['citation_validation']['passed'])

    async def test_rejected_evidence_is_not_published(self):
        from app.agents.final_answer_agent import FinalAnswerAgent
        state = GraphState('id', 'q', route='rag', draft_answer='UNSUPPORTED CLAIM', critic_passed=False)
        await FinalAnswerAgent().run(state)
        self.assertNotIn('UNSUPPORTED CLAIM', state.final_answer)
        self.assertEqual(state.evaluation['answer']['status'], 'abstained')

    def test_metrics_do_not_count_duplicate_relevance(self):
        retrieved = ['A', 'A', 'B']
        self.assertEqual(precision_at_k(retrieved, {'A'}, 2), 0.5)
        self.assertEqual(recall_at_k(retrieved, {'A'}, 2), 1)
        self.assertEqual(ndcg_at_k(retrieved, {'A'}, 2), 1)
        self.assertEqual(recall_at_k(retrieved, {'A'}, -1), 0)
        self.assertEqual(ndcg_at_k(retrieved, {'A'}, -1), 0)

    def test_evaluation_rejects_retrieval_without_citations_and_failed_critic(self):
        response = ChatResponse(conversation_id='id', route='rag', answer='Unsupported answer', agents_used=['critic'], agent_results=[AgentResult(agent='search', output='found', metadata={'documents': ['A']}), AgentResult(agent='critic', output='failed')])
        self.assertFalse(score_response(response, 'rag', True)['passed'])
        response.evaluation['citation_validation'] = {'passed': True, 'cited_labels': [1]}
        self.assertFalse(score_response(response, 'rag', True)['passed'])
        response.critic_passed = True
        self.assertTrue(score_response(response, 'rag', True)['passed'])

    async def test_retry_passes_quality_feedback_to_generator(self):
        state = GraphState('id', 'q', reranked_results=[document()], correction_attempted=True,
                           critic_feedback='Correct the date', draft_answer='Old date')
        llm = SimpleNamespace(grounded_answer=AsyncMock(return_value='Correct date [1].'))
        await RAGAgent(llm).run(state)
        context = llm.grounded_answer.call_args.kwargs['conversation_history']
        self.assertIn('Correct the date', context)
        self.assertIn('Old date', context)

    def test_index_health_detects_missing_filter_and_unknown_model(self):
        from app.evaluation.index_health import inspect_collection
        collection = Mock()
        collection.list_search_indexes.return_value = [
            {'name': settings.mongodb_search_index, 'queryable': True},
            {'name': settings.mongodb_vector_index, 'queryable': True, 'latestDefinition': {'fields': [
                {'type': 'vector', 'path': 'embedding', 'numDimensions': settings.embedding_dimensions}
            ]}},
        ]
        collection.count_documents.side_effect = [10, 8, 0]
        with patch.object(settings, 'document_scope_mode', 'owner'):
            report = inspect_collection(collection)
        self.assertFalse(report['ok'])
        self.assertIn('vector_access_filter_fields_missing', report['problems'])
        self.assertIn('documents_without_embeddings', report['problems'])
        self.assertIn('unknown_or_different_embedding_model', report['problems'])
