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


async def test_ensure_collection_creates_when_missing(store):
    await store.ensure_collection()
    store._mock.create_collection.assert_awaited_once()
    args = store._mock.create_collection.call_args.kwargs
    assert args["vectors_config"].size == 1536


async def test_ensure_collection_skips_when_exists(store):
    store._mock.collection_exists = AsyncMock(return_value=True)
    await store.ensure_collection()
    store._mock.create_collection.assert_not_called()


async def test_upsert_builds_points(store):
    await store.upsert([VectorPoint(doc_id="d", chunk_index=0, vector=[0.1, 0.2], text="t")])
    pts = store._mock.upsert.call_args.kwargs["points"]
    assert len(pts) == 1
    assert pts[0].payload["text"] == "t"


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
