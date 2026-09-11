"""Hybrid retrieval: parallel text/vector branches followed by RRF fusion."""
import asyncio
import time

from app.logger import logger
from app.models.chat_models import AgentResult, SearchResult
from app.services.retrieval_ports import NullVectorStore, VectorStorePort
from app.state import GraphState

RRF_K = 60.0


class HybridRetrieverAgent:
    """Merge candidates from multiple retrieval sources. The chat uses run_parallel; run preserves the sequential interface for experiments with existing text candidates."""

    def __init__(self, vector_store: VectorStorePort | None = None, limit: int = 8):
        """Configure the optional vector store and maximum retained results."""
        self.vector_store = vector_store or NullVectorStore()
        self.limit = limit

    async def _vector_search(self, state):
        state.retrieval_metrics.pop("vector_error", None)
        try:
            return await self.vector_store.similarity_search(
                state.metadata.get("retrieval_query") or state.user_message,
                limit=self.limit, owner_id=state.metadata.get("user_id"),
            )
        except Exception as exc:
            logger.bind(error_type=type(exc).__name__).warning("Vector search failed; continuing with full-text results.")
            state.retrieval_metrics["vector_error"] = type(exc).__name__
            return []

    async def run_parallel(self, state, text_search):
        """Run branches in independent states, avoiding concurrent writes to workflow state. Return text/hybrid traces and text candidates for the benchmark. Cancelling gather cancels both asynchronous waits."""
        def branch_state():
            return GraphState(conversation_id=state.conversation_id, user_message=state.user_message,
                              route=state.route, metadata={"user_id": state.metadata.get("user_id"),
                              "retrieval_query": state.metadata.get("retrieval_query") or state.user_message})
        text_state, vector_state = branch_state(), branch_state()
        timings = {}

        async def text_branch():
            started = time.perf_counter()
            try:
                return await text_search.run(text_state)
            except Exception as exc:
                text_state.search_results = []
                text_state.retrieval_metrics['search_error'] = type(exc).__name__
                return AgentResult(agent='search', output='search unavailable.', metadata={'error': type(exc).__name__})
            finally:
                timings['search'] = round((time.perf_counter() - started) * 1000, 2)

        async def vector_branch():
            started = time.perf_counter()
            try:
                return await self._vector_search(vector_state)
            finally:
                timings['vector_search'] = round((time.perf_counter() - started) * 1000, 2)

        started = time.perf_counter()
        text_result, vector_results = await asyncio.gather(text_branch(), vector_branch())
        timings['parallel_search'] = round((time.perf_counter() - started) * 1000, 2)
        for key in ('search_error', 'vector_error'):
            state.retrieval_metrics.pop(key, None)
        state.retrieval_metrics.update(text_state.retrieval_metrics)
        state.retrieval_metrics.update(vector_state.retrieval_metrics)
        state.search_output = text_state.search_output
        state.search_results = text_state.search_results
        started = time.perf_counter()
        hybrid_result = self.fuse(state, vector_results)
        timings['hybrid_fusion'] = round((time.perf_counter() - started) * 1000, 2)
        state.evaluation.setdefault('component_latency_ms', {}).update(timings)
        state.retrieval_metrics.update({'retrieval_execution': 'parallel', 'retrieval_latency_ms': timings,
            'retrieval_status': 'unavailable' if all(key in state.retrieval_metrics for key in ('search_error', 'vector_error'))
            else 'degraded' if any(key in state.retrieval_metrics for key in ('search_error', 'vector_error')) else 'ok'})
        hybrid_result = hybrid_result.model_copy(update={'metadata': dict(state.retrieval_metrics)})
        return text_result, hybrid_result, text_state.search_results

    async def run(self, state: GraphState) -> AgentResult:
        """Experimental compatibility: merge vector hits with previously retrieved text candidates."""
        return self.fuse(state, await self._vector_search(state))

    def fuse(self, state, vector_results):
        full_text_results = state.search_results or []
        # Fuse rankings because text and vector scores use different scales.
        merged = self._merge(full_text_results, vector_results)
        state.search_results = merged[: self.limit]
        state.retrieval_metrics.update(
            {
                "full_text_count": len(full_text_results),
                "vector_count": len(vector_results),
                "hybrid_count": len(state.search_results),
                "hybrid_fusion": "rrf",
            }
        )

        output = f"Hybrid retrieval returned {len(state.search_results)} normalized documents."
        logger.bind(
            conversation_id=state.conversation_id,
            full_text_count=len(full_text_results),
            vector_count=len(vector_results),
            hybrid_count=len(state.search_results),
        ).info("Hybrid retriever completed.")

        return AgentResult(agent="hybrid_retriever", output=output, metadata=state.retrieval_metrics)

    def _merge(self, full_text: list[SearchResult], vector: list[SearchResult]) -> list[SearchResult]:
        """Combine text and vector rankings using Reciprocal Rank Fusion."""
        fused: dict[tuple[str, str, int | None], tuple[SearchResult, float]] = {}
        for results in (full_text, vector):
            seen = set()
            for rank, item in enumerate(results, start=1):
                key = self._key(item)
                if key in seen:
                    continue
                seen.add(key)
                current_item, current_score = fused.get(key, (item, 0.0))
                if item.snippet and len(item.snippet) > len(current_item.snippet):
                    current_item = item
                fused[key] = (current_item, current_score + 1.0 / (RRF_K + rank))

        ranked = sorted(fused.values(), key=lambda pair: pair[1], reverse=True)
        return [
            item.model_copy(update={"score": fused_score})
            for item, fused_score in ranked
        ]

    def _key(self, item: SearchResult) -> tuple[str, str, int | None]:
        """Build a stable document identity for cross-branch deduplication."""
        if item.document_id:
            return (item.document_id, "", None)
        return (item.title, item.file_name or item.source, item.page_number)
