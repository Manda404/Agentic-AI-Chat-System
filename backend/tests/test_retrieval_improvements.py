import unittest

from app.agents.context_compression_agent import ContextCompressionAgent
from app.agents.hybrid_retriever_agent import HybridRetrieverAgent
from app.agents.reranker_agent import RerankerAgent
from app.memory.redis_memory import RedisMemoryService
from app.models.chat_models import SearchResult
from app.routers.ingest_router import _normalize_documents
from app.services.search_service import SearchService


class _FakeEmbeddingService:
    def __init__(self):
        self.text_batches: list[list[str]] = []

    async def embed_query(self, text: str) -> list[float]:
        return [1.0, 0.0]

    async def embed_texts(self, texts: list[str]) -> list[list[float]]:
        self.text_batches.append(texts)
        return [[0.0, 1.0] for _ in texts]


class RetrievalImprovementTests(unittest.IsolatedAsyncioTestCase):
    async def test_hybrid_merge_uses_rrf_and_rewards_cross_branch_hits(self):
        agent = HybridRetrieverAgent(limit=3)
        full_text = [
            SearchResult(document_id="a", title="A", snippet="A", score=100.0, source="text"),
            SearchResult(document_id="b", title="B", snippet="B", score=90.0, source="text"),
        ]
        vector = [
            SearchResult(document_id="b", title="B", snippet="B vector evidence", score=0.2, source="vector"),
            SearchResult(document_id="c", title="C", snippet="C", score=0.99, source="vector"),
        ]

        merged = agent._merge(full_text, vector)

        self.assertEqual([item.document_id for item in merged], ["b", "a", "c"])
        self.assertGreater(merged[0].score, merged[1].score)
        self.assertEqual(merged[0].snippet, "B vector evidence")

    async def test_reranker_reuses_stored_embeddings(self):
        embedding_service = _FakeEmbeddingService()
        reranker = RerankerAgent(embedding_service=embedding_service)
        candidates = [
            SearchResult(
                title="Stored",
                snippet="already embedded",
                score=1.0,
                source="test",
                embedding=[1.0, 0.0],
            )
        ]

        scores, used = await reranker._semantic_scores("query", candidates)

        self.assertTrue(used)
        self.assertEqual(scores, [1.0])
        self.assertEqual(embedding_service.text_batches, [])

    async def test_context_compression_selects_relevant_sentence(self):
        compressor = ContextCompressionAgent(llm_service=None, max_chars=220)  # type: ignore[arg-type]
        docs = [
            SearchResult(
                title="Guide",
                snippet=(
                    "This introduction is generic. "
                    "LangGraph orchestrates stateful multi-agent workflows. "
                    "The appendix talks about unrelated deployment notes."
                ),
                score=1.0,
                source="test",
            )
        ]

        compressed = compressor._local_compress(docs, "How does LangGraph orchestrate agents?")

        self.assertIn("LangGraph orchestrates", compressed)
        self.assertLessEqual(len(compressed), 220)

    async def test_search_service_adds_stable_document_ids(self):
        service = SearchService.__new__(SearchService)
        first = service._with_stable_id(
            {"title": "Title", "snippet": "Body", "source": "csv", "page_number": "1"}
        )
        second = service._with_stable_id(
            {"title": "Title", "snippet": "Body", "source": "csv", "page_number": "1"}
        )

        self.assertEqual(first["_id"], second["_id"])
        self.assertEqual(first["document_id"], first["_id"])

    async def test_private_document_ids_are_owner_scoped(self):
        service = SearchService.__new__(SearchService)
        alice = service._with_stable_id(
            {
                "title": "Title",
                "snippet": "Body",
                "source": "csv",
                "owner_id": "alice@example.com",
                "visibility": "private",
            }
        )
        bob = service._with_stable_id(
            {
                "title": "Title",
                "snippet": "Body",
                "source": "csv",
                "owner_id": "bob@example.com",
                "visibility": "private",
            }
        )

        self.assertNotEqual(alice["_id"], bob["_id"])

    async def test_search_access_filter_allows_owner_and_shared_documents(self):
        service = SearchService.__new__(SearchService)
        from app.config.settings import settings

        previous = settings.document_scope_mode
        try:
            settings.document_scope_mode = "owner"
            self.assertEqual(
                service._search_access_filter("person@example.com"),
                {"$or": [{"owner_id": "person@example.com"}, {"visibility": "shared"}]},
            )
        finally:
            settings.document_scope_mode = previous

    async def test_conversation_keys_are_scoped_by_owner(self):
        service = RedisMemoryService.__new__(RedisMemoryService)
        alice_key = service.conversation_key("thread", owner_id="alice@example.com")
        bob_key = service.conversation_key("thread", owner_id="bob@example.com")

        self.assertNotEqual(alice_key, bob_key)
        self.assertNotIn("alice@example.com", alice_key)

    async def test_ingest_normalization_adds_access_metadata_and_limits_snippet(self):
        from app.config.settings import settings

        previous_visibility = settings.document_default_visibility
        previous_limit = settings.max_ingested_snippet_chars
        try:
            settings.document_default_visibility = "private"
            settings.max_ingested_snippet_chars = 5
            docs = _normalize_documents(
                [{"title": " T ", "snippet": "abcdef", "category": "", "source": ""}],
                owner_id="person@example.com",
            )
        finally:
            settings.document_default_visibility = previous_visibility
            settings.max_ingested_snippet_chars = previous_limit

        self.assertEqual(docs[0]["owner_id"], "person@example.com")
        self.assertEqual(docs[0]["visibility"], "private")
        self.assertEqual(docs[0]["snippet"], "abcde")


if __name__ == "__main__":
    unittest.main()
