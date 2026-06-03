"""IngestService tests with fake embedding + vector store."""

from core.rag.ingest import IngestService
from core.tokens.counter import TokenCounter
from tests.conftest import make_settings

C = TokenCounter()


class FakeEmbedding:
    dim = 1536

    async def embed(self, texts):
        return [[float(i)] * 3 for i in range(len(texts))]


class FakeVectorStore:
    def __init__(self):
        self.deleted = []
        self.upserted = []

    async def delete_doc(self, doc_id):
        self.deleted.append(doc_id)

    async def upsert(self, points):
        self.upserted = points


def _svc(store):
    return IngestService(make_settings(ingest_chunk_tokens=20, ingest_chunk_overlap=4),
                         FakeEmbedding(), store, C)


async def test_ingest_short_doc_one_chunk():
    store = FakeVectorStore()
    doc_id, n = await _svc(store).ingest(text="a short note", title="Note")
    assert n == 1
    assert len(store.upserted) == 1
    assert store.upserted[0].payload()["source"] == "curated"
    assert store.upserted[0].title == "Note"


async def test_ingest_long_doc_multiple_chunks():
    store = FakeVectorStore()
    text = " ".join(f"word{i}" for i in range(200))
    doc_id, n = await _svc(store).ingest(text=text)
    assert n > 1
    assert len(store.upserted) == n
    # delete-before-upsert keeps the doc clean
    assert store.deleted == [doc_id]


async def test_explicit_doc_id_respected():
    store = FakeVectorStore()
    doc_id, _ = await _svc(store).ingest(text="hi", doc_id="my-id")
    assert doc_id == "my-id"


async def test_empty_text_no_chunks():
    store = FakeVectorStore()
    _doc_id, n = await _svc(store).ingest(text="   ")
    assert n == 0
    assert store.upserted == []
