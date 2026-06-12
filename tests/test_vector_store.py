"""QdrantVectorStore tests against a recording in-memory client.

The fake stores upserted points and answers scroll/query from that state, so
tests assert observable behavior (what goes in comes back out, filters
exclude, deletes remove) instead of inspecting mock call args. Only the
collection schema test asserts the wire shape — there the request IS the
contract (named dense vector + IDF sparse).
"""

import qdrant_client
import pytest

from core.rag.vector_store import Hit, QdrantVectorStore, VectorPoint


class RecordingQdrantClient:
    """In-memory stand-in for AsyncQdrantClient covering the calls the store
    makes: collections, upsert/delete/set_payload, scroll, query_points."""

    def __init__(self):
        self.collections: dict[str, dict] = {}  # name -> create kwargs
        self.points: dict[str, dict] = {}  # point id -> {"vector": ..., "payload": ...}
        self.fail = False  # flip to simulate Qdrant down

    def _check(self):
        if self.fail:
            raise RuntimeError("qdrant down")

    @staticmethod
    def _matches(payload: dict, flt) -> bool:
        if flt is None:
            return True
        return all(payload.get(c.key) == c.match.value for c in flt.must)

    def _select(self, flt, limit):
        rows = [p for p in self.points.values() if self._matches(p["payload"], flt)]
        return rows[:limit]

    # ------------------------------------------------------------ collections
    async def collection_exists(self, name):
        self._check()
        return name in self.collections

    async def create_collection(self, collection_name, **kwargs):
        self._check()
        self.collections[collection_name] = kwargs

    # ----------------------------------------------------------------- writes
    async def upsert(self, collection_name, points):
        self._check()
        for p in points:
            self.points[p.id] = {"vector": p.vector, "payload": p.payload}

    async def delete(self, collection_name, points_selector):
        self._check()
        flt = points_selector.filter
        self.points = {pid: p for pid, p in self.points.items()
                       if not self._matches(p["payload"], flt)}

    async def set_payload(self, collection_name, payload, points):
        self._check()
        for p in self.points.values():
            if self._matches(p["payload"], points):
                p["payload"].update(payload)

    # ------------------------------------------------------------------ reads
    async def scroll(self, collection_name, scroll_filter=None, limit=10,
                     with_payload=True, with_vectors=False):
        self._check()
        rows = self._select(scroll_filter, limit)
        return [_Point(payload=r["payload"]) for r in rows], None

    async def query_points(self, collection_name, *, query=None, prefetch=None,
                           using=None, limit=10, query_filter=None,
                           score_threshold=None, with_payload=True):
        self._check()
        flt = prefetch[0].filter if prefetch else query_filter
        rows = self._select(flt, limit)
        points = [_Point(payload=r["payload"], score=0.9) for r in rows]
        if score_threshold is not None:
            points = [p for p in points if p.score >= score_threshold]
        return _Response(points=points)


class _Point:
    def __init__(self, payload, score=None):
        self.payload = payload
        self.score = score


class _Response:
    def __init__(self, points):
        self.points = points


def _point(doc_id, idx, text, **kwargs):
    return VectorPoint(doc_id=doc_id, chunk_index=idx, vector=[0.1, 0.2],
                       text=text, **kwargs)


@pytest.fixture
def client():
    return RecordingQdrantClient()


@pytest.fixture
def store(monkeypatch, client):
    monkeypatch.setattr(qdrant_client, "AsyncQdrantClient", lambda url, **kw: client)
    return QdrantVectorStore("http://x", "knowledge", 1536)


# --------------------------------------------------------------- VectorPoint
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


# ----------------------------------------------------------- collection setup
async def test_ensure_collection_creates_named_dense_and_sparse(store, client):
    await store.ensure_collection()
    # The request shape IS the contract here: named dense vector of the right
    # size + sparse vector with IDF modifier (required for real BM25).
    cfg = client.collections["knowledge"]
    assert cfg["vectors_config"]["dense"].size == 1536
    assert cfg["sparse_vectors_config"]["text-sparse"].modifier is not None


async def test_ensure_collection_skips_when_exists(store, client):
    await store.ensure_collection()
    first = client.collections["knowledge"]
    await store.ensure_collection()  # second call must not recreate
    assert client.collections["knowledge"] is first


# ------------------------------------------------------------ write then read
async def test_upsert_then_scroll_doc_returns_chunks_in_order(store):
    await store.upsert([_point("d1", 1, "second chunk"),
                        _point("d1", 0, "first chunk"),
                        _point("other", 0, "unrelated")])
    payloads = await store.scroll_doc("d1")
    assert [p["text"] for p in payloads] == ["first chunk", "second chunk"]


async def test_upsert_includes_sparse_when_present(store, client):
    p = _point("d", 0, "t", sparse={"indices": [3, 7], "values": [0.4, 0.6]})
    await store.upsert([p])
    vec = client.points[p.point_id()]["vector"]
    assert vec["dense"] == [0.1, 0.2] and "text-sparse" in vec


async def test_delete_doc_removes_only_that_doc(store):
    await store.upsert([_point("d1", 0, "keep me out"), _point("d2", 0, "survivor")])
    await store.delete_doc("d1")
    assert await store.scroll_doc("d1") == []
    assert [p["text"] for p in await store.scroll_doc("d2")] == ["survivor"]


async def test_set_payload_disabled_excludes_from_filtered_search(store):
    await store.upsert([_point("d1", 0, "to disable"), _point("d2", 0, "stays on")])
    await store.set_payload("d1", {"enabled": False})
    hits = await store.search([0.1], top_k=10, enabled=True)
    assert [h.text for h in hits] == ["stays on"]


# ----------------------------------------------------------------- searching
async def test_search_maps_hits_with_scores(store):
    await store.upsert([_point("d", 0, "chunk", title="Doc")])
    hits = await store.search([0.1], top_k=1)
    assert isinstance(hits[0], Hit)
    assert hits[0].text == "chunk" and hits[0].title == "Doc"
    assert hits[0].score == 0.9


async def test_search_source_filter_excludes_other_sources(store):
    await store.upsert([_point("d1", 0, "curated chunk"),
                        _point("d2", 0, "conversation", source="conversation")])
    hits = await store.search([0.1], top_k=10, source="curated")
    assert [h.text for h in hits] == ["curated chunk"]


async def test_search_score_threshold_filters(store):
    await store.upsert([_point("d", 0, "chunk")])
    assert await store.search([0.1], top_k=1, score_threshold=0.95) == []
    assert len(await store.search([0.1], top_k=1, score_threshold=0.5)) == 1


async def test_search_returns_empty_on_error(store, client):
    client.fail = True
    assert await store.search([0.1], top_k=3, source="curated") == []


async def test_hybrid_search_returns_filtered_hits(store):
    await store.upsert([_point("d1", 0, "enabled chunk"),
                        _point("d2", 0, "disabled chunk", enabled=False)])
    hits = await store.hybrid_search([0.1], {"indices": [1], "values": [1.0]},
                                     top_k=5, source="curated", enabled=True)
    assert [h.text for h in hits] == ["enabled chunk"]


async def test_hybrid_search_dense_only_when_no_sparse(store):
    await store.upsert([_point("d", 0, "chunk")])
    hits = await store.hybrid_search([0.1], None, top_k=5, source="curated")
    assert [h.text for h in hits] == ["chunk"]


async def test_hybrid_search_empty_on_error(store, client):
    client.fail = True
    assert await store.hybrid_search([0.1], None, top_k=3) == []


# -------------------------------------------------------- slide↔code pairing
async def test_fetch_paired_filters_and_orders(store):
    await store.upsert([
        _point("c5", 1, "code part 2", content_type="code", lecture=5),
        _point("c5", 0, "code part 1", content_type="code", lecture=5),
        _point("c6", 0, "other lecture", content_type="code", lecture=6),
        _point("s5", 0, "a slide", content_type="slide", lecture=5),
        _point("c5x", 0, "disabled code", content_type="code", lecture=5,
               enabled=False),
    ])
    hits = await store.fetch_paired("code", 5, limit=10)
    assert [h.text for h in hits] == ["code part 1", "code part 2"]
    assert all(h.score == 0.0 for h in hits)  # additive, not ranked


async def test_fetch_paired_empty_on_error(store, client):
    client.fail = True
    assert await store.fetch_paired("code", 5) == []
