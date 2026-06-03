"""Live Brave Search round-trip over the real API.

Requires a valid BRAVE_API_KEY. Run with: pytest -m integration.
Skips if no key is configured.
"""

import pytest

from core.config import get_settings
from core.tools.schemas import ToolContext
from core.web.brave import build_web_search_service
from core.web.search_tool import web_search

pytestmark = pytest.mark.integration


async def test_brave_search_returns_results():
    settings = get_settings()
    service = build_web_search_service(settings)
    if service is None:
        pytest.skip("BRAVE_API_KEY not configured")

    try:
        results = await service.search("OpenAI", count=3, freshness="pm")
    finally:
        await service.aclose()

    assert results, "expected at least one web result"
    top = results[0]
    assert top.url.startswith("http")
    assert top.title


async def test_web_search_tool_formats_live_results():
    settings = get_settings()
    service = build_web_search_service(settings)
    if service is None:
        pytest.skip("BRAVE_API_KEY not configured")

    ctx = ToolContext(
        settings=settings,
        embedding_service=None,
        vector_store=None,
        session_id="s",
        user_key="u",
        channel_id="c",
        web_search_service=service,
    )
    try:
        out = await web_search({"query": "Python programming language", "count": 3}, ctx)
    finally:
        await service.aclose()

    assert out.startswith("[1]")
    assert "http" in out
    assert "temporarily unavailable" not in out
