"""Shared retrieval wiring for chat and its benchmark."""
import time

from app.agents.search_agent import SearchAgent
from app.agents.hybrid_retriever_agent import HybridRetrieverAgent
from app.agents.reranker_agent import RerankerAgent
from app.agents.context_compression_agent import ContextCompressionAgent
from app.config.settings import settings
from app.models.chat_models import AgentResult
from app.services.mongo_vector_store import MongoVectorStore
from app.state import GraphState


class RetrievalPipeline:
    def __init__(self, search_service, embedding_service):
        self.search = SearchAgent(search_service)
        self.hybrid = HybridRetrieverAgent(MongoVectorStore(search_service, embedding_service))
        self.reranker = RerankerAgent(
            max_results=settings.max_rag_documents,
            embedding_service=embedding_service if settings.semantic_reranker_enabled else None,
        )
        self.compressor = ContextCompressionAgent(None, max_chars=settings.max_rag_context_chars)

    async def run(self, state: GraphState) -> None:
        text_result, hybrid_result, _ = await self.hybrid.run_parallel(state, self.search)
        state.record_result(text_result)
        state.record_result(hybrid_result)
        for name, component in (('reranker', self.reranker), ('context_compression', self.compressor)):
            started = time.perf_counter()
            try:
                result = await component.run(state)
            except Exception as exc:
                if name == 'reranker':
                    state.reranked_results = state.search_results[:settings.max_rag_documents]
                else:
                    raise
                state.retrieval_metrics[f'{name}_error'] = type(exc).__name__
                result = AgentResult(agent=name, output=f'{name} unavailable.', metadata={'error': type(exc).__name__})
            state.record_result(result)
            state.evaluation.setdefault('component_latency_ms', {})[name] = round((time.perf_counter() - started) * 1000, 2)
