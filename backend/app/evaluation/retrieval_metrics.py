"""Information-retrieval metrics for ranked titles and binary relevance. retrieved preserves ranking order, relevant contains ground-truth titles, and k sets evaluation depth. Duplicate hits retain rank positions but earn no repeated relevance credit."""

import math
from typing import Sequence, Set


def precision_at_k(retrieved: Sequence[str], relevant: Set[str], k: int) -> float:
    """Relevant hits among the first k positions, divided by fixed k even if fewer results are returned. This avoids rewarding stages that return too few candidates."""
    if k <= 0:
        return 0.0
    top_k = retrieved[:k]
    hits = len(set(top_k) & relevant)
    return hits / k


def recall_at_k(retrieved: Sequence[str], relevant: Set[str], k: int) -> float:
    """Fraction of relevant documents retrieved within the first k positions."""
    if not relevant or k <= 0:
        return 0.0
    top_k = retrieved[:k]
    hits = len(set(top_k) & relevant)
    return hits / len(relevant)


def reciprocal_rank(retrieved: Sequence[str], relevant: Set[str]) -> float:
    """Reciprocal rank of the first relevant hit, or zero when absent. Average across cases for MRR."""
    for rank, title in enumerate(retrieved, start=1):
        if title in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], relevant: Set[str], k: int) -> float:
    """Normalized discounted cumulative gain: reward relevant hits near the top, normalized by the best possible ranking."""
    if k <= 0:
        return 0.0
    top_k = retrieved[:k]
    seen = set()
    dcg = 0.0
    for rank, title in enumerate(top_k, start=1):
        if title in relevant and title not in seen:
            dcg += 1.0 / math.log2(rank + 1)
        seen.add(title)
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


def mean(values: Sequence[float]) -> float:
    """Arithmetic mean, or 0.0 for an empty list."""
    return sum(values) / len(values) if values else 0.0
