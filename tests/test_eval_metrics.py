"""Retrieval metrics — textbook cases."""

import math

from core.eval import metrics as M

# ranked keys (rank 0 = top); golden: key -> graded relevance
A, B, C, D, E = "a", "b", "c", "d", "e"
RANKED = [A, B, C, D, E]
GOLDEN = {A: 1, C: 1, E: 1}  # 3 relevant, at ranks 0,2,4


def test_recall_at_k():
    assert M.recall_at_k(RANKED, GOLDEN, 1) == 1 / 3   # only A in top-1
    assert M.recall_at_k(RANKED, GOLDEN, 3) == 2 / 3   # A,C in top-3
    assert M.recall_at_k(RANKED, GOLDEN, 5) == 1.0     # all 3 by top-5


def test_precision_at_k():
    assert M.precision_at_k(RANKED, GOLDEN, 1) == 1.0  # A relevant
    assert M.precision_at_k(RANKED, GOLDEN, 2) == 0.5  # A rel, B not
    assert M.precision_at_k(RANKED, GOLDEN, 3) == 2 / 3


def test_hit_rate_at_k():
    assert M.hit_rate_at_k(RANKED, GOLDEN, 1) == 1.0
    assert M.hit_rate_at_k([B, D], GOLDEN, 2) == 0.0   # none relevant


def test_mrr():
    assert M.mrr(RANKED, GOLDEN) == 1.0                # first relevant at rank 0
    assert M.mrr([B, C, A], GOLDEN) == 1 / 2           # first relevant (C) at rank 1


def test_ndcg_graded():
    # ranked A(1),B(0),C(1) ; ideal ordering of grades [1,1,1]
    ndcg = M.ndcg_at_k([A, B, C], {A: 1, C: 1, D: 1}, 3)
    dcg = 1 / math.log2(2) + 0 + 1 / math.log2(4)
    idcg = 1 / math.log2(2) + 1 / math.log2(3) + 1 / math.log2(4)
    assert abs(ndcg - dcg / idcg) < 1e-9


def test_no_golden_returns_none():
    assert M.recall_at_k(RANKED, {}, 3) is None
    assert M.mrr(RANKED, {}) is None
    assert M.ndcg_at_k(RANKED, {}, 3) is None


def test_compute_bundle_shape():
    out = M.compute_retrieval_metrics(RANKED, GOLDEN, [1, 3])
    assert set(out) == {"recall", "precision", "ndcg", "hit_rate", "mrr"}
    assert out["recall"]["3"] == 2 / 3 and out["mrr"] == 1.0
