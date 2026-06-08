"""Adaptive-RAG routing in the pipeline (_retrieve_knowledge): simple skips,
medium uses fused top-k, complex reranks."""

from types import SimpleNamespace

from core.pipeline import _format_knowledge, _retrieve_knowledge, _source_label
from core.rag.classifier import COMPLEX, MEDIUM, SIMPLE
from core.rag.vector_store import Hit
from tests.conftest import make_settings

H = [Hit(text=f"d{i}", score=1.0, title=None, payload={}) for i in range(5)]


def test_source_label_uses_deck_and_slide_title():
    hit = Hit(text="…", score=1.0, title="W14_例外處理.pptx",
              payload={"metadata": {"title": "錯誤的種類"}})
    assert _source_label(hit) == "W14 例外處理 — 錯誤的種類"
    # injected citation carries the readable label, not the filename
    assert "(W14 例外處理 — 錯誤的種類)" in _format_knowledge([hit])


def test_source_label_fallbacks():
    # no slide title -> deck only
    assert _source_label(Hit(text="x", score=1.0, title="W01_intro.pptx",
                             payload={})) == "W01 intro"
    # nothing at all -> untitled
    assert _source_label(Hit(text="x", score=1.0, title=None, payload={})) == "untitled"


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


class FakePairStore:
    """Returns configured code hits from fetch_paired keyed by lecture."""

    def __init__(self, by_lecture):
        self._by = by_lecture

    async def fetch_paired(self, content_type, lecture, *, limit=5):
        return list(self._by.get((content_type, lecture), []))[:limit]


def _deps(tier, retriever, reranker=None, settings=None, vector_store=None):
    return SimpleNamespace(
        classifier=FakeClassifier(tier), retriever=retriever,
        reranker=reranker, settings=settings or make_settings(),
        vector_store=vector_store,
    )


def _slide(doc_id, lecture):
    return Hit(text=f"slide {lecture}", score=1.0, title=f"W{lecture:02d}_主題.pptx",
               payload={"content_type": "slide", "lecture": lecture,
                        "doc_id": doc_id, "chunk_index": 0})


def _code(doc_id, lecture, fname):
    return Hit(text=f"code {lecture}", score=0.0, title=fname,
               payload={"content_type": "code", "lecture": lecture, "source_file": fname,
                        "doc_id": doc_id, "chunk_index": 0})


async def test_simple_skips_retrieval():
    r = FakeRetriever(H)
    out, trace = await _retrieve_knowledge(_deps(SIMPLE, r), "q")
    assert out == "" and r.top_k is None
    assert trace.tier == SIMPLE and trace.candidates == []


async def test_medium_uses_medium_top_k_no_rerank():
    r, rk = FakeRetriever(H), FakeReranker()
    out, trace = await _retrieve_knowledge(_deps(MEDIUM, r, rk, make_settings(rag_medium_top_k=3)), "q")
    assert r.top_k == 3
    assert not rk.called
    assert out.count("[") == 3
    # medium: all retrieved candidates are included, none reranked
    assert trace.tier == MEDIUM and not trace.reranked
    assert len(trace.candidates) == 3 and all(c.included for c in trace.candidates)


async def test_complex_retrieves_candidates_then_reranks():
    r, rk = FakeRetriever(H), FakeReranker()
    s = make_settings(rag_complex_candidates=5, rag_complex_top_k=2)
    out, trace = await _retrieve_knowledge(_deps(COMPLEX, r, rk, s), "q")
    assert r.top_k == 5  # larger candidate pool
    assert rk.called
    assert out.count("[") == 2  # truncated after rerank
    # trace keeps all 5 candidates; exactly 2 made the final top-k
    assert trace.reranked and len(trace.candidates) == 5
    assert sum(c.included for c in trace.candidates) == 2


async def test_complex_without_reranker_uses_fused_topk():
    r = FakeRetriever(H)
    s = make_settings(rag_complex_candidates=5, rag_complex_top_k=2)
    out, trace = await _retrieve_knowledge(_deps(COMPLEX, r, None, s), "q")
    assert r.top_k == 5
    assert out.count("[") == 2
    assert not trace.reranked and sum(c.included for c in trace.candidates) == 2


async def test_no_classifier_returns_empty():
    deps = SimpleNamespace(classifier=None, retriever=None, reranker=None,
                           settings=make_settings())
    out, trace = await _retrieve_knowledge(deps, "q")
    assert out == "" and trace is None


# ---------------------------------------------------- slide → code binding
async def test_slide_pairs_code():
    r = FakeRetriever([_slide("s5", 5)])
    store = FakePairStore({("code", 5): [_code("c5", 5, "W05_條件判斷.py")]})
    s = make_settings(rag_medium_top_k=1, rag_pair_code_enabled=True)
    out, trace = await _retrieve_knowledge(_deps(MEDIUM, r, None, s, store), "q")
    # the paired code is injected alongside the slide
    assert out.count("[") == 2 and "code: W05_條件判斷.py" in out and "code 5" in out
    paired = [c for c in trace.candidates if c.paired]
    assert len(paired) == 1 and paired[0].included and paired[0].content_type == "code"


async def test_pairing_dedup_skips_already_retrieved():
    code = _code("c5", 5, "W05_條件判斷.py")
    r = FakeRetriever([_slide("s5", 5), code])
    store = FakePairStore({("code", 5): [code]})  # same chunk already retrieved
    s = make_settings(rag_medium_top_k=2, rag_pair_code_enabled=True)
    out, trace = await _retrieve_knowledge(_deps(MEDIUM, r, None, s, store), "q")
    assert out.count("[") == 2  # not injected a second time
    assert not any(c.paired for c in trace.candidates)


async def test_pairing_disabled_flag():
    r = FakeRetriever([_slide("s5", 5)])
    store = FakePairStore({("code", 5): [_code("c5", 5, "W05.py")]})
    s = make_settings(rag_medium_top_k=1, rag_pair_code_enabled=False)
    out, trace = await _retrieve_knowledge(_deps(MEDIUM, r, None, s, store), "q")
    assert out.count("[") == 1 and "code:" not in out
    assert not any(c.paired for c in trace.candidates)
