"""ToolRegistry tests."""

import pytest

from core.tools.schemas import Tool
from core.tools.registry import ToolRegistry


async def _noop(args, ctx):
    return "ok"


def _tool(name="t1"):
    return Tool(name=name, description="d", parameters={"type": "object", "properties": {}},
                handler=_noop)


def test_register_get_all():
    reg = ToolRegistry()
    reg.register(_tool("a"))
    reg.register(_tool("b"))
    assert reg.get("a") is not None
    assert reg.get("missing") is None
    assert {t.name for t in reg.all()} == {"a", "b"}


def test_duplicate_raises():
    reg = ToolRegistry()
    reg.register(_tool("a"))
    with pytest.raises(ValueError):
        reg.register(_tool("a"))


def test_openai_schema_shape():
    reg = ToolRegistry()
    reg.register(_tool("a"))
    schema = reg.openai_schema()
    assert schema[0]["type"] == "function"
    assert schema[0]["function"]["name"] == "a"
    assert "parameters" in schema[0]["function"]
