"""ToolRunner loop tests with a scripted ChatService."""

import pytest

from core.llm.base import ChatServiceError
from core.tools.loop import ToolRunner
from core.tools.registry import ToolRegistry
from core.tools.schemas import ChatCompletionResult, Tool, ToolCall, ToolContext
from tests.conftest import make_settings


class ScriptedChat:
    """Returns queued ChatCompletionResults in order; records tool lists seen."""

    def __init__(self, results, supports_tools=True):
        self._results = list(results)
        self.supports_tools = supports_tools
        self.tools_seen = []

    async def complete(self, session_id, messages, tools=None):
        self.tools_seen.append(tools)
        self.last_messages = messages
        return self._results.pop(0)

    async def generate_reply(self, session_id, messages):
        return "plain reply"


def _ctx(progress=None, correlation_id="cid1"):
    return ToolContext(settings=make_settings(), embedding_service=None,
                       vector_store=None, session_id="s1", user_key="u", channel_id="c",
                       correlation_id=correlation_id, progress=progress)


class FakeProgressEmitter:
    def __init__(self):
        self.events = []  # list of (correlation_id, kind, tool)

    async def emit(self, correlation_id, kind, tool=None):
        self.events.append((correlation_id, kind, tool))


def _text(t):
    return ChatCompletionResult(text=t, tool_calls=[],
                                raw_assistant_message={"role": "assistant", "content": t})


def _call(name="echo", args=None, cid="c1"):
    return ChatCompletionResult(
        text=None, tool_calls=[ToolCall(id=cid, name=name, arguments=args or {})],
        raw_assistant_message={"role": "assistant", "tool_calls": [
            {"id": cid, "type": "function", "function": {"name": name, "arguments": "{}"}}]},
    )


def _registry(handler, name="echo"):
    reg = ToolRegistry()
    reg.register(Tool(name=name, description="d",
                      parameters={"type": "object", "properties": {}}, handler=handler))
    return reg


async def test_fallback_when_tools_disabled():
    chat = ScriptedChat([_text("hi")], supports_tools=True)
    runner = ToolRunner(chat, ToolRegistry(), make_settings(enable_tools=False))
    out = await runner.run("s1", [{"role": "user", "content": "x"}], _ctx())
    assert out == "hi"
    assert chat.tools_seen == [None]  # no tools passed


async def test_fallback_when_provider_unsupported():
    chat = ScriptedChat([_text("hi")], supports_tools=False)
    runner = ToolRunner(chat, ToolRegistry(), make_settings())
    out = await runner.run("s1", [{"role": "user", "content": "x"}], _ctx())
    assert out == "hi"


async def test_tool_call_then_final_text():
    called = {}

    async def handler(args, ctx):
        called["args"] = args
        return "tool says hello"

    chat = ScriptedChat([_call("echo", {"q": "hi"}), _text("final answer")])
    runner = ToolRunner(chat, _registry(handler), make_settings())
    out = await runner.run("s1", [{"role": "user", "content": "x"}], _ctx())
    assert out == "final answer"
    assert called["args"] == {"q": "hi"}
    # the working messages now contain assistant(tool_calls) + tool result
    roles = [m["role"] for m in chat.last_messages]
    assert "assistant" in roles and "tool" in roles
    tool_msg = [m for m in chat.last_messages if m["role"] == "tool"][0]
    assert tool_msg["tool_call_id"] == "c1"
    assert tool_msg["content"] == "tool says hello"


async def test_unknown_tool_reported_not_fatal():
    chat = ScriptedChat([_call("missing"), _text("recovered")])
    runner = ToolRunner(chat, ToolRegistry(), make_settings())
    out = await runner.run("s1", [{"role": "user", "content": "x"}], _ctx())
    assert out == "recovered"
    tool_msg = [m for m in chat.last_messages if m["role"] == "tool"][0]
    assert "unknown tool" in tool_msg["content"]


async def test_handler_error_reported_not_fatal():
    async def boom(args, ctx):
        raise RuntimeError("kaboom")

    chat = ScriptedChat([_call("echo"), _text("ok")])
    runner = ToolRunner(chat, _registry(boom), make_settings())
    out = await runner.run("s1", [{"role": "user", "content": "x"}], _ctx())
    assert out == "ok"
    tool_msg = [m for m in chat.last_messages if m["role"] == "tool"][0]
    assert "error: kaboom" in tool_msg["content"]


async def test_max_iterations_converges():
    async def handler(args, ctx):
        return "again"

    # always returns a tool call -> hits the cap, then a tool-free pass
    results = [_call("echo")] * 2 + [_text("converged")]
    chat = ScriptedChat(results)
    runner = ToolRunner(chat, _registry(handler), make_settings(tool_max_iterations=2))
    out = await runner.run("s1", [{"role": "user", "content": "x"}], _ctx())
    assert out == "converged"
    assert chat.tools_seen[-1] is None  # final convergence pass has no tools


async def test_progress_events_emitted_around_tool():
    from shared.progress import THINKING, TOOL_END, TOOL_START

    async def handler(args, ctx):
        return "tool result"

    chat = ScriptedChat([_call("echo"), _text("done")])
    runner = ToolRunner(chat, _registry(handler), make_settings())
    emitter = FakeProgressEmitter()
    out = await runner.run("s1", [{"role": "user", "content": "x"}], _ctx(emitter))
    assert out == "done"
    kinds = [(kind, tool) for _cid, kind, tool in emitter.events]
    assert kinds == [
        (THINKING, None),
        (TOOL_START, "echo"),
        (TOOL_END, "echo"),
        (THINKING, None),
    ]
    assert all(cid == "cid1" for cid, _k, _t in emitter.events)


async def test_no_progress_emitter_is_noop():
    # ctx with progress=None must not raise (default path).
    async def handler(args, ctx):
        return "r"

    chat = ScriptedChat([_call("echo"), _text("ok")])
    runner = ToolRunner(chat, _registry(handler), make_settings())
    out = await runner.run("s1", [{"role": "user", "content": "x"}], _ctx(progress=None))
    assert out == "ok"


async def test_chat_service_error_propagates():
    class BoomChat:
        supports_tools = True

        async def complete(self, session_id, messages, tools=None):
            raise ChatServiceError("llm down")

        async def generate_reply(self, session_id, messages):
            raise ChatServiceError("llm down")

    runner = ToolRunner(BoomChat(), ToolRegistry(), make_settings())
    with pytest.raises(ChatServiceError):
        await runner.run("s1", [{"role": "user", "content": "x"}], _ctx())
