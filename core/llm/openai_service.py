"""OpenAI provider."""

from core.config import Settings
from core.llm.base import ChatService, ChatServiceError, _require


class OpenAIChatService(ChatService):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=_require(settings.openai_api_key, "OPENAI_API_KEY")
        )

    async def generate_reply(self, session_id: str, messages: list[dict]) -> str:
        from openai import OpenAIError

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
