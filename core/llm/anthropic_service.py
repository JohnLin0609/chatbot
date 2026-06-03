"""Anthropic Claude provider."""

from core.config import Settings
from core.llm.base import ChatService, ChatServiceError, _require
from core.llm.messages import split_system


class AnthropicChatService(ChatService):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        from anthropic import AsyncAnthropic

        self._client = AsyncAnthropic(
            api_key=_require(settings.anthropic_api_key, "ANTHROPIC_API_KEY")
        )

    async def generate_reply(self, session_id: str, messages: list[dict]) -> str:
        from anthropic import AnthropicError

        system_text, turns = split_system(messages)
        try:
            response = await self._client.messages.create(
                model=self._settings.model_name,
                max_tokens=self._settings.max_tokens,
                system=[
                    {
                        "type": "text",
                        "text": system_text,
                        # Cache the (stable) system prompt to cut cost/latency.
                        "cache_control": {"type": "ephemeral"},
                    }
                ],
                messages=turns,
            )
        except AnthropicError as exc:
            raise ChatServiceError(str(exc)) from exc

        return "".join(b.text for b in response.content if b.type == "text")
