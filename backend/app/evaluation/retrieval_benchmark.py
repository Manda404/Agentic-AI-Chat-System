"""Measure retrieval quality separately from end-to-end response contracts. Run text/vector retrieval with RRF and reranking against labeled cases, reporting Precision@k, Recall@k, MRR and NDCG@k. Requires Atlas, embeddings, prepared indexes and the ingested sample corpus. Run python -m app.evaluation.retrieval_benchmark; add --verbose for per-case and per-stage results."""

import argparse
import asyncio
from dataclasses import dataclass

from app.agents.hybrid_retriever_agent import HybridRetrieverAgent
from app.agents.reranker_agent import RerankerAgent
from app.config.settings import settings
from app.evaluation.retrieval_cases import GOLD_RETRIEVAL_CASES, RetrievalGoldCase
from app.evaluation.retrieval_metrics import mean, ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank
from app.services.embedding_service import HuggingFaceEmbeddingService
from app.services.retrieval_pipeline import RetrievalPipeline
from app.agents.search_agent import SearchAgent
from app.services.search_service import SearchService
from app.state import GraphState

STAGES = ("full_text", "hybrid", "reranked")


@dataclass
class CaseResult:
    case: RetrievalGoldCase
    titles_by_stage: dict[str, list[str]]


@dataclass
class StageScore:
    stage: str
    precision_at_k: float
    recall_at_k: float
    mrr: float
    ndcg_at_k: float


def _build_pipeline() -> tuple[SearchService, HybridRetrieverAgent, RerankerAgent]:
    """Build the same retrieval components used by ChatWorkflow."""
    search_service = SearchService()
    embedding_service = HuggingFaceEmbeddingService()
    pipeline = RetrievalPipeline(search_service, embedding_service)
    return search_service, pipeline.hybrid, pipeline.reranker


async def _run_case(
    search_service: SearchService,
    hybrid_agent: HybridRetrieverAgent,
    reranker_agent: RerankerAgent,
    case: RetrievalGoldCase,
    owner_id: str | None = None,
) -> CaseResult:
    """Run the three retrieval stages for one question and return ranked titles at each stage."""
    state = GraphState(conversation_id="retrieval-benchmark", user_message=case.query,
                       metadata={"user_id": owner_id} if owner_id else {})

    _, _, full_text_results = await hybrid_agent.run_parallel(state, SearchAgent(search_service))
    if state.retrieval_metrics.get("search_error"):
        raise RuntimeError("Benchmark full-text stage failed.")
    full_text_titles = [item.title for item in full_text_results]

    if state.retrieval_metrics.get("vector_error"):
        raise RuntimeError(f"Benchmark vector stage failed: {state.retrieval_metrics['vector_error']}")
    hybrid_titles = [item.title for item in state.search_results]

    await reranker_agent.run(state)
    if settings.semantic_reranker_enabled and state.search_results and not state.retrieval_metrics.get("semantic_reranking_used"):
        raise RuntimeError("Benchmark semantic reranking failed; results would be misleading.")
    reranked_titles = [item.title for item in state.reranked_results]

    return CaseResult(
        case=case,
        titles_by_stage={
            "full_text": full_text_titles,
            "hybrid": hybrid_titles,
            "reranked": reranked_titles,
        },
    )


def _score_stage(results: list[CaseResult], stage: str, k: int) -> StageScore:
    precisions, recalls, rrs, ndcgs = [], [], [], []
    for result in results:
        retrieved = result.titles_by_stage[stage]
        relevant = result.case.relevant_titles
        precisions.append(precision_at_k(retrieved, relevant, k))
        recalls.append(recall_at_k(retrieved, relevant, k))
        rrs.append(reciprocal_rank(retrieved, relevant))
        ndcgs.append(ndcg_at_k(retrieved, relevant, k))
    return StageScore(
        stage=stage,
        precision_at_k=mean(precisions),
        recall_at_k=mean(recalls),
        mrr=mean(rrs),
        ndcg_at_k=mean(ndcgs),
    )


def _print_summary(scores: list[StageScore], k: int) -> None:
    header = f"{'Stage':<12} {'Precision@' + str(k):<14} {'Recall@' + str(k):<12} {'MRR':<8} {'NDCG@' + str(k):<10}"
    print(header)
    print("-" * len(header))
    for score in scores:
        print(
            f"{score.stage:<12} {score.precision_at_k:<14.2f} {score.recall_at_k:<12.2f} "
            f"{score.mrr:<8.2f} {score.ndcg_at_k:<10.2f}"
        )


def _print_verbose(results: list[CaseResult], k: int) -> None:
    print()
    for result in results:
        print(f"• {result.case.name} — \"{result.case.query}\"")
        print(f"  attendu     : {sorted(result.case.relevant_titles)}")
        for stage in STAGES:
            titles = result.titles_by_stage[stage][:k]
            hit = any(title in result.case.relevant_titles for title in titles)
            marker = "OK" if hit else "MISS"
            print(f"  {stage:<10}[{marker}] : {titles}")
        print()


async def main(verbose: bool = False, k: int | None = None, owner_id: str | None = None) -> list[StageScore]:
    k = settings.max_rag_documents if k is None else k
    if k <= 0:
        raise ValueError("k must be positive.")
    search_service, hybrid_agent, reranker_agent = _build_pipeline()

    try:
        if not search_service.available:
            raise RuntimeError(
                "MongoDB Atlas unavailable (MONGODB_URI). The benchmark requires a real "
                "connection and the ingested sample dataset (POST /ingest/sample-data)."
            )

        results = [
            await _run_case(search_service, hybrid_agent, reranker_agent, case, owner_id=owner_id)
            for case in GOLD_RETRIEVAL_CASES
        ]

        scores = [_score_stage(results, stage, k) for stage in STAGES]

        print(f"Benchmark retrieval — {len(GOLD_RETRIEVAL_CASES)} cas, k={k}\n")
        _print_summary(scores, k)
        if verbose:
            _print_verbose(results, k)

        return scores
    finally:
        search_service.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Retrieval quality benchmark (Precision/Recall/MRR/NDCG).")
    parser.add_argument("--verbose", action="store_true", help="Show details for each case and stage.")
    parser.add_argument("--k", type=int, default=None, help="Evaluation depth (default: MAX_RAG_DOCUMENTS).")
    parser.add_argument("--owner-id", help="Owner of the evaluation corpus in owner mode.")
    args = parser.parse_args()
    asyncio.run(main(verbose=args.verbose, k=args.k, owner_id=args.owner_id))
