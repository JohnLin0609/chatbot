"""GoldenStore CRUD + replace-set of relevant chunks."""

from core.eval.golden_store import GoldenStore


async def test_create_list_get(sessionmaker):
    store = GoldenStore(sessionmaker)
    created = await store.create(
        query="how long for a refund?", reference_answer="14 days", notes="n",
        relevant_chunks=[{"doc_id": "d1", "chunk_index": 0, "relevance": 3}],
    )
    assert created["query"] == "how long for a refund?"
    assert created["relevant_chunks"] == [
        {"doc_id": "d1", "chunk_index": 0, "relevance": 3}]

    listed = await store.list()
    assert len(listed) == 1 and listed[0]["reference_answer"] == "14 days"
    got = await store.get(created["id"])
    assert got["id"] == created["id"]


async def test_update_replaces_chunks(sessionmaker):
    store = GoldenStore(sessionmaker)
    c = await store.create(query="q", relevant_chunks=[{"doc_id": "d1", "chunk_index": 0}])
    upd = await store.update(
        c["id"], query="q2", reference_answer="r",
        relevant_chunks=[{"doc_id": "d2", "chunk_index": 1, "relevance": 2}],
    )
    assert upd["query"] == "q2" and upd["reference_answer"] == "r"
    assert upd["relevant_chunks"] == [
        {"doc_id": "d2", "chunk_index": 1, "relevance": 2}]


async def test_set_relevant_chunks_and_delete(sessionmaker):
    store = GoldenStore(sessionmaker)
    c = await store.create(query="q")
    assert c["relevant_chunks"] == []
    set_ = await store.set_relevant_chunks(c["id"], [{"doc_id": "d1", "chunk_index": 5}])
    assert set_["relevant_chunks"][0]["chunk_index"] == 5

    assert await store.delete(c["id"]) is True
    assert await store.get(c["id"]) is None
    assert await store.delete(9999) is False
