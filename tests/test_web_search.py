"""web_search handler + registration-gate tests with a fake Brave service."""

from core.tools.registry import ToolRegistry, register_default_tools
from core.tools.schemas import ToolContext
from core.web.brave import BraveResult, WebSearchError
from core.web.search_tool import web_search
from tests.conftest import make_settings


class FakeBraveService:
    def __init__(self, results=None, error=False):
        self._results = results or []
        self._error = error
        self.call = None

    async def search(self, query, count=None, freshness=None):
        if self._error:
            raise WebSearchError("brave down")
        self.call = dict(query=query, count=count, freshness=freshness)
        return self._results


def _ctx(service, settings=None):
    return ToolContext(
        settings=settings or make_settings(),
        embedding_service=None,
        vector_store=None,
        session_id="s",
        user_key="u",
        channel_id="c",
        web_search_service=service,
    )


async def test_formats_results_with_url():
    svc = FakeBraveService(
        [BraveResult(title="Python 3.13", url="https://ex.com/py", description="released")]
    )
    out = await web_search({"query": "python release"}, _ctx(svc))
    assert "[1]" in out
    assert "Python 3.13" in out
    assert "https://ex.com/py" in out
    assert "released" in out


async def test_default_count_from_settings():
    svc = FakeBraveService([])
    await web_search({"query": "x"}, _ctx(svc, make_settings(brave_search_count=7)))
    assert svc.call["count"] == 7


async def test_passes_count_and_freshness_through():
    svc = FakeBraveService([])
    await web_search({"query": "x", "count": 3, "freshness": "pw"}, _ctx(svc))
    assert svc.call["count"] == 3
    assert svc.call["freshness"] == "pw"


async def test_no_results_message():
    out = await web_search({"query": "x"}, _ctx(FakeBraveService([])))
    assert out == "No web results found."


async def test_degrades_on_error():
    out = await web_search({"query": "x"}, _ctx(FakeBraveService(error=True)))
    assert "temporarily unavailable" in out


async def test_empty_query():
    out = await web_search({"query": "  "}, _ctx(FakeBraveService([])))
    assert "error" in out


async def test_missing_service_degrades():
    out = await web_search({"query": "x"}, _ctx(None))
    assert "temporarily unavailable" in out


def test_registered_only_when_key_present():
    with_key = ToolRegistry()
    register_default_tools(with_key, make_settings(brave_api_key="k"))
    assert with_key.get("web_search") is not None

    without_key = ToolRegistry()
    register_default_tools(without_key, make_settings(brave_api_key=""))
    assert without_key.get("web_search") is None
    # The unconditional RAG tool is still registered either way.
    assert without_key.get("search_knowledge") is not None
