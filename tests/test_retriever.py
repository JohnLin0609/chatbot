"""RagRetriever: query embedding (dense + sparse) + hybrid search."""

from core.rag.retriever import RagRetriever
from core.rag.vector_store import Hit
from tests.conftest import FakeEmbedding, FakeSparseEmbedder, make_settings


class RecordingStore:
    def __init__(self, hits):
        self._hits = hits
        self.call = None

    async def hybrid_search(self, dense, sparse, top_k, *, source=None,
                            enabled=True, prefetch_limit=50):
        self.call = dict(sparse=sparse, top_k=top_k, source=source, enabled=enabled)
        return self._hits


async def test_retrieve_embeds_dense_and_sparse():
    store = RecordingStore([Hit(text="t", score=1.0, title="T", payload={})])
    r = RagRetriever(store, FakeEmbedding(), FakeSparseEmbedder(), make_settings())
    hits = await r.retrieve("q", top_k=3)
    assert hits[0].text == "t"
    assert store.call["sparse"] is not None  # hybrid path
    assert store.call["source"] == "curated" and store.call["enabled"] is True
    assert store.call["top_k"] == 3


async def test_retrieve_dense_only_when_no_sparse():
    store = RecordingStore([])
    r = RagRetriever(store, FakeEmbedding(), None, make_settings())
    await r.retrieve("q", top_k=2)
    assert store.call["sparse"] is None  # degrades to dense-only
