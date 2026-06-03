"""OpenAIChatService tests with the OpenAI SDK mocked (no network)."""

from unittest.mock import MagicMock

import openai
import pytest

from core.config import Provider, Settings
from core.llm import OpenAIChatService
from core.llm.base import ChatServiceError


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, provider=Provider.openai, openai_api_key="x", **kwargs)


MESSAGES = [
    {"role": "system", "content": "you are helpful"},
    {"role": "user", "content": "hi there"},
]


class _FakeMessage:
    content = "hello from openai"


class _FakeChoice:
    message = _FakeMessage()


class _FakeResponse:
    choices = [_FakeChoice()]


@pytest.fixture
def captured_create(monkeypatch):
    """Patch AsyncOpenAI; capture kwargs passed to chat.completions.create."""
    captured = {}

    async def fake_create(**kwargs):
        captured.update(kwargs)
        return _FakeResponse()

    fake_client = MagicMock()
    fake_client.chat.completions.create = fake_create
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: fake_client)
    return captured


async def test_returns_assistant_text(captured_create):
    svc = OpenAIChatService(_settings(model="gpt-5.4-mini"))
    reply = await svc.generate_reply("s1", MESSAGES)
    assert reply == "hello from openai"


async def test_passes_model_and_message_list(captured_create):
    svc = OpenAIChatService(_settings(model="gpt-5.4-mini"))
    await svc.generate_reply("s1", MESSAGES)

    assert captured_create["model"] == "gpt-5.4-mini"
    # GPT-5 series requires max_completion_tokens, not max_tokens.
    assert captured_create["max_completion_tokens"] == 1024
    assert "max_tokens" not in captured_create
    assert captured_create["messages"] == MESSAGES


async def test_sdk_error_becomes_chat_service_error(monkeypatch):
    async def boom(**kwargs):
        raise openai.OpenAIError("upstream failed")

    fake_client = MagicMock()
    fake_client.chat.completions.create = boom
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: fake_client)

    svc = OpenAIChatService(_settings())
    with pytest.raises(ChatServiceError):
        await svc.generate_reply("s1", MESSAGES)


# ------------------------------------------------------------- complete() + tools
class _ToolCallFn:
    def __init__(self, name, arguments):
        self.name = name
        self.arguments = arguments


class _ToolCall:
    def __init__(self, id, name, arguments):
        self.id = id
        self.function = _ToolCallFn(name, arguments)


class _Msg:
    def __init__(self, content, tool_calls=None):
        self.content = content
        self.tool_calls = tool_calls

    def model_dump(self, exclude_none=False):
        d = {"role": "assistant", "content": self.content}
        if self.tool_calls:
            d["tool_calls"] = [
                {"id": tc.id, "type": "function",
                 "function": {"name": tc.function.name, "arguments": tc.function.arguments}}
                for tc in self.tool_calls
            ]
        return d


class _Resp:
    def __init__(self, msg):
        self.choices = [type("C", (), {"message": msg})]


def _patch_create(monkeypatch, response, captured):
    async def fake_create(**kwargs):
        captured.update(kwargs)
        return response

    fake_client = MagicMock()
    fake_client.chat.completions.create = fake_create
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: fake_client)


def test_supports_tools():
    assert OpenAIChatService(_settings()).supports_tools is True


async def test_complete_passes_tools(monkeypatch):
    captured = {}
    _patch_create(monkeypatch, _Resp(_Msg("hi")), captured)
    svc = OpenAIChatService(_settings())
    tools = [{"type": "function", "function": {"name": "t", "description": "", "parameters": {}}}]
    result = await svc.complete("s1", MESSAGES, tools=tools)
    assert captured["tools"] == tools
    assert captured["tool_choice"] == "auto"
    assert result.text == "hi"
    assert result.tool_calls == []


async def test_complete_parses_tool_calls(monkeypatch):
    msg = _Msg(None, tool_calls=[_ToolCall("call_1", "search_knowledge", '{"query": "refund"}')])
    _patch_create(monkeypatch, _Resp(msg), {})
    svc = OpenAIChatService(_settings())
    result = await svc.complete("s1", MESSAGES, tools=[{"x": 1}])
    assert len(result.tool_calls) == 1
    tc = result.tool_calls[0]
    assert tc.id == "call_1" and tc.name == "search_knowledge"
    assert tc.arguments == {"query": "refund"}
    # raw assistant message preserved for stacking back
    assert result.raw_assistant_message["tool_calls"][0]["id"] == "call_1"


async def test_complete_no_tools_when_none(monkeypatch):
    captured = {}
    _patch_create(monkeypatch, _Resp(_Msg("plain")), captured)
    svc = OpenAIChatService(_settings())
    await svc.complete("s1", MESSAGES, tools=None)
    assert "tools" not in captured
