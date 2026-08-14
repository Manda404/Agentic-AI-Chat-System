"""
Métriques standard de recherche d'information (IR), appliquées à des
listes de titres de documents classés par pertinence décroissante.

Toutes les fonctions prennent :
- `retrieved`  : les titres renvoyés par le retrieval, DANS L'ORDRE.
- `relevant`   : l'ensemble des titres considérés comme pertinents (ground truth).
- `k`          : la profondeur d'évaluation (on ignore ce qui est classé après k).

Pertinence binaire uniquement (pertinent / non pertinent) : pas de score
gradué, ce qui garde le jeu de référence simple à maintenir.
"""

import math
from typing import Sequence, Set


def precision_at_k(retrieved: Sequence[str], relevant: Set[str], k: int) -> float:
    """
    Part de documents pertinents parmi les k premiers résultats.

    Convention IR standard : on divise toujours par k (fixe), pas par le
    nombre de résultats réellement retournés. Un étage qui renvoie moins
    de k candidats (ex: full-text seul sur un petit corpus) ne doit pas
    paraître artificiellement plus précis qu'un étage qui en renvoie k —
    sinon la comparaison entre étages n'est plus juste, ce qui est
    justement le but de ce benchmark.
    """
    if k <= 0:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for title in top_k if title in relevant)
    return hits / k


def recall_at_k(retrieved: Sequence[str], relevant: Set[str], k: int) -> float:
    """Part des documents pertinents effectivement retrouvés dans les k premiers résultats."""
    if not relevant:
        return 0.0
    top_k = retrieved[:k]
    hits = sum(1 for title in top_k if title in relevant)
    return hits / len(relevant)


def reciprocal_rank(retrieved: Sequence[str], relevant: Set[str]) -> float:
    """1 / rang du premier document pertinent trouvé (0 si aucun). Base du MRR une fois moyenné sur plusieurs cas."""
    for rank, title in enumerate(retrieved, start=1):
        if title in relevant:
            return 1.0 / rank
    return 0.0


def ndcg_at_k(retrieved: Sequence[str], relevant: Set[str], k: int) -> float:
    """
    Normalized Discounted Cumulative Gain : récompense les documents
    pertinents trouvés tôt plus que ceux trouvés tard, normalisé par le
    meilleur classement possible (tous les documents pertinents en tête).
    """
    top_k = retrieved[:k]
    dcg = sum(
        (1.0 if title in relevant else 0.0) / math.log2(rank + 1)
        for rank, title in enumerate(top_k, start=1)
    )
    ideal_hits = min(len(relevant), k)
    idcg = sum(1.0 / math.log2(rank + 1) for rank in range(1, ideal_hits + 1))
    return dcg / idcg if idcg > 0 else 0.0


def mean(values: Sequence[float]) -> float:
    """Moyenne simple, 0.0 si la liste est vide (évite une ZeroDivisionError sur un jeu de cas vide)."""
    return sum(values) / len(values) if values else 0.0
