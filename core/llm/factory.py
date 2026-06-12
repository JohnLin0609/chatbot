"""Construct the ChatService for the configured provider."""

from core.config import Provider, Settings
from core.llm.anthropic_service import AnthropicChatService
from core.llm.base import ChatService
from core.llm.gemini_service import GeminiChatService
from core.llm.ollama_service import OllamaChatService
from core.llm.openai_service import OpenAIChatService
from core.llm.resilience import ResilientChatService

_SERVICES: dict[Provider, type[ChatService]] = {
    Provider.anthropic: AnthropicChatService,
    Provider.openai: OpenAIChatService,
    Provider.gemini: GeminiChatService,
    Provider.ollama: OllamaChatService,
}


def build_chat_service(settings: Settings) -> ChatService:
    return ResilientChatService(_SERVICES[settings.provider](settings), settings)
