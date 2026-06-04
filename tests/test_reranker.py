"""Reranker ordering logic (model stubbed) + build gate."""

from core.rag.reranker import Qwen3Reranker, build_reranker
from core.rag.vector_store import Hit
from tests.conftest import make_settings


def _stub_reranker(scores):
    # Bypass __init__ (which would load torch/transformers); stub the scorer.
    r = object.__new__(Qwen3Reranker)
    r._score = lambda query, docs: scores
    return r


async def test_rerank_sorts_by_score_and_truncates():
    r = _stub_reranker([0.1, 0.9, 0.5])
    hits = [Hit(text=t, score=0, title=None, payload={}) for t in ("a", "b", "c")]
    out = await r.rerank("q", hits, top_k=2)
    assert [h.text for h in out] == ["b", "c"]


async def test_rerank_empty():
    assert await _stub_reranker([]).rerank("q", [], top_k=3) == []


def test_build_reranker_disabled_returns_none():
    assert build_reranker(make_settings(rag_reranker_enabled=False)) is None
