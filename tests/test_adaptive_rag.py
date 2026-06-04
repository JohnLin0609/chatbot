"""Adaptive-RAG routing in the pipeline (_retrieve_knowledge): simple skips,
medium uses fused top-k, complex reranks."""

from types import SimpleNamespace

from core.pipeline import _retrieve_knowledge
from core.rag.classifier import COMPLEX, MEDIUM, SIMPLE
from core.rag.vector_store import Hit
from tests.conftest import make_settings

H = [Hit(text=f"d{i}", score=1.0, title=None, payload={}) for i in range(5)]


class FakeClassifier:
    def __init__(self, tier):
        self._tier = tier

    async def classify(self, q):
        return self._tier


class FakeRetriever:
    def __init__(self, hits):
        self._hits = hits
        self.top_k = None

    async def retrieve(self, q, *, top_k):
        self.top_k = top_k
        return self._hits[:top_k]


class FakeReranker:
    def __init__(self):
        self.called = False

    async def rerank(self, q, hits, top_k):
        self.called = True
        return list(reversed(hits))[:top_k]


def _deps(tier, retriever, reranker=None, settings=None):
    return SimpleNamespace(
        classifier=FakeClassifier(tier), retriever=retriever,
        reranker=reranker, settings=settings or make_settings(),
    )


async def test_simple_skips_retrieval():
    r = FakeRetriever(H)
    out = await _retrieve_knowledge(_deps(SIMPLE, r), "q")
    assert out == "" and r.top_k is None


async def test_medium_uses_medium_top_k_no_rerank():
    r, rk = FakeRetriever(H), FakeReranker()
    out = await _retrieve_knowledge(_deps(MEDIUM, r, rk, make_settings(rag_medium_top_k=3)), "q")
    assert r.top_k == 3
    assert not rk.called
    assert out.count("[") == 3


async def test_complex_retrieves_candidates_then_reranks():
    r, rk = FakeRetriever(H), FakeReranker()
    s = make_settings(rag_complex_candidates=5, rag_complex_top_k=2)
    out = await _retrieve_knowledge(_deps(COMPLEX, r, rk, s), "q")
    assert r.top_k == 5  # larger candidate pool
    assert rk.called
    assert out.count("[") == 2  # truncated after rerank


async def test_complex_without_reranker_uses_fused_topk():
    r = FakeRetriever(H)
    s = make_settings(rag_complex_candidates=5, rag_complex_top_k=2)
    out = await _retrieve_knowledge(_deps(COMPLEX, r, None, s), "q")
    assert r.top_k == 5
    assert out.count("[") == 2


async def test_no_classifier_returns_empty():
    deps = SimpleNamespace(classifier=None, retriever=None, reranker=None,
                           settings=make_settings())
    assert await _retrieve_knowledge(deps, "q") == ""
