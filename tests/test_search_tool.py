"""search_knowledge handler tests with fake embedding + vector store."""

from core.rag.search_tool import search_knowledge
from core.rag.vector_store import Hit
from core.tools.schemas import ToolContext
from tests.conftest import make_settings


class FakeEmbedding:
    dim = 1536

    async def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeVectorStore:
    def __init__(self, hits=None, error=False):
        self._hits = hits or []
        self._error = error
        self.search_kwargs = None

    async def search(self, vector, top_k, *, source=None, score_threshold=None):
        if self._error:
            raise RuntimeError("qdrant down")
        self.search_kwargs = dict(top_k=top_k, source=source, score_threshold=score_threshold)
        return self._hits


def _ctx(vector_store, settings=None):
    return ToolContext(settings=settings or make_settings(), embedding_service=FakeEmbedding(),
                       vector_store=vector_store, session_id="s", user_key="u", channel_id="c")


async def test_formats_hits_without_metadata():
    vs = FakeVectorStore([Hit(text="refunds within 30 days", score=0.82, title="Refund Policy", payload={})])
    out = await search_knowledge({"query": "refund"}, _ctx(vs))
    assert "[1]" in out and "Refund Policy" in out and "refunds within 30 days" in out
    assert "0.82" in out


async def test_filters_curated_and_uses_top_k():
    vs = FakeVectorStore([])
    await search_knowledge({"query": "x", "top_k": 3}, _ctx(vs))
    assert vs.search_kwargs["source"] == "curated"
    assert vs.search_kwargs["top_k"] == 3


async def test_default_top_k_from_settings():
    vs = FakeVectorStore([])
    await search_knowledge({"query": "x"}, _ctx(vs, make_settings(rag_top_k=7)))
    assert vs.search_kwargs["top_k"] == 7


async def test_no_hits_message():
    out = await search_knowledge({"query": "x"}, _ctx(FakeVectorStore([])))
    assert out == "No relevant knowledge found."


async def test_degrades_on_error():
    out = await search_knowledge({"query": "x"}, _ctx(FakeVectorStore(error=True)))
    assert "temporarily unavailable" in out


async def test_empty_query():
    out = await search_knowledge({"query": "  "}, _ctx(FakeVectorStore([])))
    assert "error" in out


def test_registered_as_default_tool():
    from core.tools.registry import ToolRegistry, register_default_tools

    reg = ToolRegistry()
    register_default_tools(reg)
    assert reg.get("search_knowledge") is not None
