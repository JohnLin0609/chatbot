"""OpenAIChatService tests with the OpenAI SDK mocked (no network)."""

from unittest.mock import MagicMock

import openai
import pytest

from app.chat_service import ChatServiceError, OpenAIChatService
from app.config import Provider, Settings


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, provider=Provider.openai, openai_api_key="x", **kwargs)


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
    reply = await svc.generate_reply("s1", "hi there")
    assert reply == "hello from openai"


async def test_sends_model_and_system_then_user(captured_create):
    svc = OpenAIChatService(_settings(model="gpt-5.4-mini"))
    await svc.generate_reply("s1", "hi there")

    assert captured_create["model"] == "gpt-5.4-mini"
    assert captured_create["max_tokens"] == 1024
    roles = [m["role"] for m in captured_create["messages"]]
    assert roles == ["system", "user"]
    assert captured_create["messages"][-1]["content"] == "hi there"


async def test_sdk_error_becomes_chat_service_error(monkeypatch):
    async def boom(**kwargs):
        raise openai.OpenAIError("upstream failed")

    fake_client = MagicMock()
    fake_client.chat.completions.create = boom
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: fake_client)

    svc = OpenAIChatService(_settings())
    with pytest.raises(ChatServiceError):
        await svc.generate_reply("s1", "hi")
