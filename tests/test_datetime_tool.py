"""current_datetime tool: format, default tz, override, bad-tz fallback, registration."""

import re

from core.tools.datetime_tool import current_datetime
from core.tools.registry import ToolRegistry, register_default_tools
from core.tools.schemas import ToolContext
from tests.conftest import make_settings


def _ctx():
    return ToolContext(
        settings=make_settings(), embedding_service=None, vector_store=None,
        session_id="s", user_key="u", channel_id="c",
    )


async def test_defaults_to_taipei_and_formats():
    out = await current_datetime({}, _ctx())
    # ISO date + weekday + +0800 offset + the tz label
    assert re.match(r"\d{4}-\d{2}-\d{2} \w+ \d{2}:\d{2}:\d{2}", out)
    assert "+0800" in out and "Asia/Taipei" in out


async def test_explicit_timezone_override():
    out = await current_datetime({"timezone": "UTC"}, _ctx())
    assert "+0000" in out and "(UTC)" in out


async def test_bad_timezone_falls_back_to_taipei():
    out = await current_datetime({"timezone": "Not/AZone"}, _ctx())
    assert "+0800" in out and "Asia/Taipei" in out


async def test_registered_by_default_no_gate():
    reg = ToolRegistry()
    register_default_tools(reg, make_settings())
    assert reg.get("current_datetime") is not None
    # exposed in the OpenAI schema the model sees
    assert any(t["function"]["name"] == "current_datetime" for t in reg.openai_schema())
