"""Chat service with pluggable LLM providers.

A single `ChatService` interface (`generate_reply`) is implemented by one class
per provider. `build_chat_service()` picks the implementation from settings.
"""

from abc import ABC, abstractmethod

from app.config import Provider, Settings


class ChatServiceError(Exception):
    """Raised when the upstream LLM call fails (bad key, network, etc.)."""


def _require(value: str, name: str) -> str:
    if not value:
        raise ChatServiceError(f"{name} is required for the selected provider")
    return value


def _build_messages(message: str) -> list[dict[str, str]]:
    """Build the OpenAI/Ollama-style message list for a single user turn.

    TODO(next-stage): load prior messages for the session and prepend them here
    so the conversation has memory. For now each request is independent.
    """
    return [{"role": "user", "content": message}]


class ChatService(ABC):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @abstractmethod
    async def generate_reply(self, session_id: str, message: str) -> str:
        """Return an assistant reply for a single user message."""


class AnthropicChatService(ChatService):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(
            api_key=_require(settings.anthropic_api_key, "ANTHROPIC_API_KEY")
        )

    async def generate_reply(self, session_id: str, message: str) -> str:
        from anthropic import AnthropicError

        try:
            response = await self._client.messages.create(
                model=self._settings.model_name,
                max_tokens=self._settings.max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": self._settings.system_prompt,
                        # Cache the (stable) system prompt to cut cost/latency.
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=_build_messages(message),
            )
        except AnthropicError as exc:
            raise ChatServiceError(str(exc)) from exc

        return "".join(b.text for b in response.content if b.type == "text")


class OpenAIChatService(ChatService):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=_require(settings.openai_api_key, "OPENAI_API_KEY")
        )

    async def generate_reply(self, session_id: str, message: str) -> str:
        from openai import OpenAIError

        messages = [
            {"role": "system", "content": self._settings.system_prompt},
            *_build_messages(message),
        ]
        try:
            response = await self._client.chat.completions.create(
                model=self._settings.model_name,
                # Newer OpenAI models (GPT-5 / o-series) require
                # max_completion_tokens; max_tokens is rejected.
                max_completion_tokens=self._settings.max_tokens,
                messages=messages,
            )
        except OpenAIError as exc:
            raise ChatServiceError(str(exc)) from exc

        return response.choices[0].message.content or ""


class GeminiChatService(ChatService):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        from google import genai

        self._genai = genai
        self._client = genai.Client(
            api_key=_require(settings.gemini_api_key, "GEMINI_API_KEY")
        )

    async def generate_reply(self, session_id: str, message: str) -> str:
        from google.genai import types
        from google.genai.errors import APIError

        try:
            response = await self._client.aio.models.generate_content(
                model=self._settings.model_name,
                contents=message,
                config=types.GenerateContentConfig(
                    system_instruction=self._settings.system_prompt,
                    max_output_tokens=self._settings.max_tokens,
                ),
            )
        except APIError as exc:
            raise ChatServiceError(str(exc)) from exc

        return response.text or ""


class OllamaChatService(ChatService):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        from ollama import AsyncClient

        self._client = AsyncClient(host=settings.ollama_host)

    async def generate_reply(self, session_id: str, message: str) -> str:
        from ollama import ResponseError

        messages = [
            {"role": "system", "content": self._settings.system_prompt},
            *_build_messages(message),
        ]
        try:
            response = await self._client.chat(
                model=self._settings.model_name,
                messages=messages,
                options={"num_predict": self._settings.max_tokens},
            )
        except (ResponseError, ConnectionError) as exc:
            raise ChatServiceError(str(exc)) from exc

        return response["message"]["content"]


_SERVICES: dict[Provider, type[ChatService]] = {
    Provider.anthropic: AnthropicChatService,
    Provider.openai: OpenAIChatService,
    Provider.gemini: GeminiChatService,
    Provider.ollama: OllamaChatService,
}


def build_chat_service(settings: Settings) -> ChatService:
    """Construct the ChatService for the configured provider."""
    return _SERVICES[settings.provider](settings)
