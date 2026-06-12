"""Provider factory tests."""

import pytest

from core.llm import (
    AnthropicChatService,
    ChatServiceError,
    GeminiChatService,
    OllamaChatService,
    OpenAIChatService,
    build_chat_service,
)
from core.llm.resilience import ResilientChatService
from core.config import Provider, Settings


def _settings(**kwargs) -> Settings:
    return Settings(_env_file=None, **kwargs)


@pytest.mark.parametrize(
    "provider, kwargs, expected",
    [
        (Provider.anthropic, {"anthropic_api_key": "x"}, AnthropicChatService),
        (Provider.openai, {"openai_api_key": "x"}, OpenAIChatService),
        (Provider.gemini, {"gemini_api_key": "x"}, GeminiChatService),
        (Provider.ollama, {}, OllamaChatService),
    ],
)
def test_factory_builds_expected_service(provider, kwargs, expected):
    svc = build_chat_service(_settings(provider=provider, **kwargs))
    # Every provider is wrapped with timeout/retry resilience.
    assert isinstance(svc, ResilientChatService)
    assert isinstance(svc._inner, expected)


@pytest.mark.parametrize(
    "provider, key_name",
    [
        (Provider.anthropic, "anthropic_api_key"),
        (Provider.openai, "openai_api_key"),
        (Provider.gemini, "gemini_api_key"),
    ],
)
def test_missing_key_raises_clear_error(provider, key_name):
    # Force the relevant key empty regardless of the host environment.
    with pytest.raises(ChatServiceError):
        build_chat_service(_settings(provider=provider, **{key_name: ""}))
