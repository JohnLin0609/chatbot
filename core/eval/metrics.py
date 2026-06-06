"""Retrieval metrics over a ranked result list vs a golden relevant set.

Pure functions, no I/O. `ranked` is the system's ranked list of chunk keys
(rank 0 = top). `golden` maps a chunk key -> graded relevance (>0 = relevant).
A "key" is any hashable identifier, e.g. (doc_id, chunk_index).
"""

import math


def _relevant_keys(golden: dict) -> set:
    return {k for k, g in golden.items() if g and g > 0}


def recall_at_k(ranked: list, golden: dict, k: int) -> float | None:
    rel = _relevant_keys(golden)
    if not rel:
        return None  # undefined without any relevant chunk
    hit = sum(1 for key in ranked[:k] if key in rel)
    return hit / len(rel)


def precision_at_k(ranked: list, golden: dict, k: int) -> float | None:
    rel = _relevant_keys(golden)
    if not rel or k <= 0:
        return None
    hit = sum(1 for key in ranked[:k] if key in rel)
    return hit / k


def hit_rate_at_k(ranked: list, golden: dict, k: int) -> float | None:
    rel = _relevant_keys(golden)
    if not rel:
        return None
    return 1.0 if any(key in rel for key in ranked[:k]) else 0.0


def mrr(ranked: list, golden: dict) -> float | None:
    rel = _relevant_keys(golden)
    if not rel:
        return None
    for i, key in enumerate(ranked):
        if key in rel:
            return 1.0 / (i + 1)
    return 0.0


def ndcg_at_k(ranked: list, golden: dict, k: int) -> float | None:
    """Graded NDCG@k: DCG = sum rel_i / log2(i+2); IDCG = ideal ordering."""
    if not _relevant_keys(golden):
        return None
    gains = [float(golden.get(key, 0) or 0) for key in ranked[:k]]
    dcg = sum(g / math.log2(i + 2) for i, g in enumerate(gains))
    ideal = sorted((float(g) for g in golden.values() if g and g > 0), reverse=True)[:k]
    idcg = sum(g / math.log2(i + 2) for i, g in enumerate(ideal))
    if idcg == 0:
        return None
    return dcg / idcg


def compute_retrieval_metrics(ranked: list, golden: dict, k_values: list[int]) -> dict:
    """Bundle every metric. @k metrics are keyed by k (as a string for JSON)."""
    return {
        "recall": {str(k): recall_at_k(ranked, golden, k) for k in k_values},
        "precision": {str(k): precision_at_k(ranked, golden, k) for k in k_values},
        "ndcg": {str(k): ndcg_at_k(ranked, golden, k) for k in k_values},
        "hit_rate": {str(k): hit_rate_at_k(ranked, golden, k) for k in k_values},
        "mrr": mrr(ranked, golden),
    }
