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
