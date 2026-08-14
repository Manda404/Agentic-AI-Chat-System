"""
Benchmark de qualité du retrieval.

Contrairement à `evaluator.py` (qui vérifie le comportement bout-en-bout
du `ChatWorkflow` : route, présence d'une réponse, critic observé), cet
outil isole la question spécifique : **est-ce que les BONS documents
remontent, et dans le BON ordre ?**

Il exécute les VRAIS agents de production (`SearchAgent` -> via
`SearchService`, `HybridRetrieverAgent`, `RerankerAgent`), câblés
exactement comme `ChatWorkflow.__init__` le fait, contre MongoDB Atlas.
Ce n'est PAS un test unitaire avec des fakes : un benchmark contre des
fakes ne mesurerait rien de réel. Il faut donc :

1. Une vraie connexion MongoDB Atlas (`MONGODB_URI` dans `.env`) ;
2. Le jeu de données d'exemple déjà ingéré : `POST /ingest/sample-data`
   (ou tes propres documents + tes propres cas dans `retrieval_cases.py`).

Il mesure Precision@k / Recall@k / MRR / NDCG@k à TROIS étages :
- `full_text`  : SearchAgent seul (MongoDB Atlas Search, mots-clés)
- `hybrid`     : + HybridRetrieverAgent (fusion avec la recherche vectorielle)
- `reranked`   : + RerankerAgent (score lexical + sémantique, troncature finale)

Comparer les trois étages répond à une question concrète : est-ce que
chaque étage AMÉLIORE vraiment le classement, ou juste le complexifie ?
C'est aussi ce qui permet de calibrer `SEMANTIC_WEIGHT` (voir
RAG_SYSTEM.md, erreur #6) sur des données réelles plutôt qu'à l'aveugle.

Usage :
    cd backend
    .venv/bin/python -m app.evaluation.retrieval_benchmark          # résumé agrégé
    .venv/bin/python -m app.evaluation.retrieval_benchmark --verbose # + détail par cas
"""

import argparse
import asyncio
from dataclasses import dataclass

from app.agents.hybrid_retriever_agent import HybridRetrieverAgent
from app.agents.reranker_agent import RerankerAgent
from app.config.settings import settings
from app.evaluation.retrieval_cases import GOLD_RETRIEVAL_CASES, RetrievalGoldCase
from app.evaluation.retrieval_metrics import mean, ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank
from app.services.embedding_service import HuggingFaceEmbeddingService
from app.services.mongo_vector_store import MongoVectorStore
from app.services.search_service import SearchService
from app.state import GraphState

STAGES = ("full_text", "hybrid", "reranked")


def _dedupe_preserve_order(titles: list[str]) -> list[str]:
    """
    Retire les doublons de titre en gardant le meilleur rang de chacun.

    `SearchService.search()` ne déduplique pas (contrairement à
    `HybridRetrieverAgent._merge()`) : si le même document a été ingéré
    plusieurs fois (ex: sample-data relancé), il apparaît plusieurs fois
    dans les résultats full-text bruts. Sans cette étape, les métriques
    IR (pensées pour des documents distincts) seraient faussées — par
    exemple un recall@k qui dépasse 1.0.
    """
    seen: set[str] = set()
    deduped: list[str] = []
    for title in titles:
        if title in seen:
            continue
        seen.add(title)
        deduped.append(title)
    return deduped


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
    """Instancie les agents avec EXACTEMENT le même câblage que `ChatWorkflow.__init__`."""
    search_service = SearchService()
    embedding_service = HuggingFaceEmbeddingService()
    hybrid_agent = HybridRetrieverAgent(
        vector_store=MongoVectorStore(search_service, embedding_service)
    )
    reranker_agent = RerankerAgent(
        max_results=settings.max_rag_documents,
        embedding_service=embedding_service if settings.semantic_reranker_enabled else None,
    )
    return search_service, hybrid_agent, reranker_agent


async def _run_case(
    search_service: SearchService,
    hybrid_agent: HybridRetrieverAgent,
    reranker_agent: RerankerAgent,
    case: RetrievalGoldCase,
) -> CaseResult:
    """Exécute les 3 étages réels du pipeline pour une question, retourne les titres classés à chaque étage."""
    state = GraphState(conversation_id="retrieval-benchmark", user_message=case.query)

    full_text_results = await search_service.search(case.query)
    state.search_results = full_text_results
    full_text_titles = [item.title for item in full_text_results]

    await hybrid_agent.run(state)
    hybrid_titles = [item.title for item in state.search_results]

    await reranker_agent.run(state)
    reranked_titles = [item.title for item in state.reranked_results]

    return CaseResult(
        case=case,
        titles_by_stage={
            "full_text": _dedupe_preserve_order(full_text_titles),
            "hybrid": _dedupe_preserve_order(hybrid_titles),
            "reranked": _dedupe_preserve_order(reranked_titles),
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
    header = f"{'Étage':<12} {'Precision@' + str(k):<14} {'Recall@' + str(k):<12} {'MRR':<8} {'NDCG@' + str(k):<10}"
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


async def main(verbose: bool = False, k: int | None = None) -> list[StageScore]:
    k = k or settings.max_rag_documents
    search_service, hybrid_agent, reranker_agent = _build_pipeline()

    if not search_service.available:
        raise RuntimeError(
            "MongoDB Atlas indisponible (MONGODB_URI). Le benchmark a besoin d'une vraie "
            "connexion et du jeu de données d'exemple déjà ingéré (POST /ingest/sample-data)."
        )

    results = [
        await _run_case(search_service, hybrid_agent, reranker_agent, case)
        for case in GOLD_RETRIEVAL_CASES
    ]

    scores = [_score_stage(results, stage, k) for stage in STAGES]

    print(f"Benchmark retrieval — {len(GOLD_RETRIEVAL_CASES)} cas, k={k}\n")
    _print_summary(scores, k)
    if verbose:
        _print_verbose(results, k)

    return scores


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Benchmark de qualité du retrieval (Precision/Recall/MRR/NDCG).")
    parser.add_argument("--verbose", action="store_true", help="Affiche le détail par cas et par étage.")
    parser.add_argument("--k", type=int, default=None, help="Profondeur d'évaluation (défaut: MAX_RAG_DOCUMENTS).")
    args = parser.parse_args()
    asyncio.run(main(verbose=args.verbose, k=args.k))
