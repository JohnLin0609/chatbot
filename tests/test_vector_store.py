"""QdrantVectorStore tests with the qdrant client mocked."""

from unittest.mock import AsyncMock, MagicMock

import qdrant_client
import pytest

from core.rag.vector_store import Hit, QdrantVectorStore, VectorPoint


@pytest.fixture
def store(monkeypatch):
    client = MagicMock()
    client.collection_exists = AsyncMock(return_value=False)
    client.create_collection = AsyncMock()
    client.upsert = AsyncMock()
    client.delete = AsyncMock()
    client.query_points = AsyncMock(return_value=MagicMock(points=[]))
    monkeypatch.setattr(qdrant_client, "AsyncQdrantClient", lambda url, **kw: client)
    s = QdrantVectorStore("http://x", "knowledge", 1536)
    s._mock = client
    return s


def test_point_id_deterministic():
    p1 = VectorPoint(doc_id="d", chunk_index=0, vector=[0.1], text="t")
    p2 = VectorPoint(doc_id="d", chunk_index=0, vector=[0.2], text="other")
    assert p1.point_id() == p2.point_id()
    p3 = VectorPoint(doc_id="d", chunk_index=1, vector=[0.1], text="t")
    assert p1.point_id() != p3.point_id()


def test_payload_has_source():
    p = VectorPoint(doc_id="d", chunk_index=0, vector=[0.1], text="t", title="T")
    pl = p.payload()
    assert pl["source"] == "curated"
    assert pl["doc_id"] == "d" and pl["title"] == "T"


def test_payload_classification_fields_default_none_and_set():
    bare = VectorPoint(doc_id="d", chunk_index=0, vector=[0.1], text="t").payload()
    for k in ("content_type", "lecture", "topic", "language", "source_file"):
        assert bare[k] is None
    p = VectorPoint(doc_id="d", chunk_index=0, vector=[0.1], text="t",
                    content_type="code", lecture=5, topic="conditionals",
                    language="python", source_file="W05_條件判斷.py").payload()
    assert p["content_type"] == "code" and p["lecture"] == 5
    assert p["language"] == "python" and p["source_file"] == "W05_條件判斷.py"


async def test_fetch_paired_filters_and_maps(store):
    pt = MagicMock(payload={"text": "code body", "title": "W05_條件判斷.py",
                            "chunk_index": 0, "content_type": "code", "lecture": 5})
    store._mock.scroll = AsyncMock(return_value=([pt], None))
    hits = await store.fetch_paired("code", 5, limit=3)
    assert hits and hits[0].text == "code body" and hits[0].score == 0.0
    flt = store._mock.scroll.call_args.kwargs["scroll_filter"]
    keys = {c.key for c in flt.must}
    assert keys == {"content_type", "lecture", "source", "enabled"}


async def test_fetch_paired_empty_on_error(store):
    store._mock.scroll = AsyncMock(side_effect=RuntimeError("down"))
    assert await store.fetch_paired("code", 5) == []


async def test_ensure_collection_creates_named_dense_and_sparse(store):
    await store.ensure_collection()
    store._mock.create_collection.assert_awaited_once()
    args = store._mock.create_collection.call_args.kwargs
    assert args["vectors_config"]["dense"].size == 1536
    # sparse vector configured with IDF modifier (required for real BM25)
    sparse_cfg = args["sparse_vectors_config"]["text-sparse"]
    assert sparse_cfg.modifier is not None


async def test_ensure_collection_skips_when_exists(store):
    store._mock.collection_exists = AsyncMock(return_value=True)
    await store.ensure_collection()
    store._mock.create_collection.assert_not_called()


async def test_upsert_builds_named_vectors(store):
    await store.upsert([VectorPoint(doc_id="d", chunk_index=0, vector=[0.1, 0.2], text="t")])
    pts = store._mock.upsert.call_args.kwargs["points"]
    assert len(pts) == 1
    assert pts[0].payload["text"] == "t"
    assert pts[0].vector["dense"] == [0.1, 0.2]  # named dense vector


async def test_upsert_includes_sparse_when_present(store):
    p = VectorPoint(doc_id="d", chunk_index=0, vector=[0.1], text="t",
                    sparse={"indices": [3, 7], "values": [0.4, 0.6]})
    await store.upsert([p])
    vec = store._mock.upsert.call_args.kwargs["points"][0].vector
    assert "dense" in vec and "text-sparse" in vec


async def test_hybrid_search_uses_prefetch_and_fusion(store):
    r = MagicMock(score=0.5, payload={"text": "c", "title": "D"})
    store._mock.query_points = AsyncMock(return_value=MagicMock(points=[r]))
    hits = await store.hybrid_search([0.1], {"indices": [1], "values": [1.0]}, top_k=3,
                                     source="curated")
    assert hits and hits[0].text == "c"
    kwargs = store._mock.query_points.call_args.kwargs
    assert len(kwargs["prefetch"]) == 2  # dense + sparse branches
    assert kwargs["query"] is not None  # FusionQuery


async def test_hybrid_search_dense_only_when_no_sparse(store):
    await store.hybrid_search([0.1], None, top_k=3, source="curated")
    kwargs = store._mock.query_points.call_args.kwargs
    assert len(kwargs["prefetch"]) == 1  # dense branch only


async def test_hybrid_search_empty_on_error(store):
    store._mock.query_points = AsyncMock(side_effect=RuntimeError("down"))
    assert await store.hybrid_search([0.1], None, top_k=3) == []


async def test_search_passes_source_filter(store):
    await store.search([0.1], top_k=3, source="curated", score_threshold=0.5)
    kwargs = store._mock.query_points.call_args.kwargs
    assert kwargs["limit"] == 3
    assert kwargs["score_threshold"] == 0.5
    assert kwargs["query_filter"] is not None  # source filter built


async def test_search_returns_empty_on_error(store):
    store._mock.query_points = AsyncMock(side_effect=RuntimeError("no collection"))
    hits = await store.search([0.1], top_k=3, source="curated")
    assert hits == []


async def test_search_maps_hits(store):
    r = MagicMock(score=0.82, payload={"text": "chunk", "title": "Doc"})
    store._mock.query_points = AsyncMock(return_value=MagicMock(points=[r]))
    hits = await store.search([0.1], top_k=1)
    assert hits == [Hit(text="chunk", score=0.82, title="Doc", payload={"text": "chunk", "title": "Doc"})]
