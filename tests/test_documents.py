"""DocumentStore CRUD + toggle (in-memory SQLite)."""

from core.documents.store import DocumentStore


async def test_upsert_insert_then_update(sessionmaker):
    store = DocumentStore(sessionmaker)
    d = await store.upsert("doc1", title="T", doc_type="slides", chunk_count=3)
    assert d["doc_id"] == "doc1"
    assert d["doc_type"] == "slides"
    assert d["chunk_count"] == 3
    assert d["enabled"] is True

    d2 = await store.upsert("doc1", title="T2", doc_type="slides", chunk_count=5)
    assert d2["title"] == "T2"
    assert d2["chunk_count"] == 5
    assert len(await store.list()) == 1  # same doc_id -> updated, not duplicated


async def test_list_and_get(sessionmaker):
    store = DocumentStore(sessionmaker)
    await store.upsert("a", title="A", doc_type="prose", chunk_count=1)
    await store.upsert("b", title="B", doc_type="token", chunk_count=2)
    docs = await store.list()
    assert {d["doc_id"] for d in docs} == {"a", "b"}
    assert (await store.get("a"))["title"] == "A"
    assert await store.get("missing") is None


async def test_set_enabled(sessionmaker):
    store = DocumentStore(sessionmaker)
    await store.upsert("a", title="A", doc_type="prose", chunk_count=1)
    d = await store.set_enabled("a", False)
    assert d["enabled"] is False
    assert (await store.get("a"))["enabled"] is False
    assert await store.set_enabled("missing", False) is None
