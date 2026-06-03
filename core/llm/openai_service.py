"""OpenAI provider."""

import json

from core.config import Settings
from core.llm.base import ChatService, ChatServiceError, _require
from core.tools.schemas import ChatCompletionResult, ToolCall


class OpenAIChatService(ChatService):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        from openai import AsyncOpenAI

        self._client = AsyncOpenAI(
            api_key=_require(settings.openai_api_key, "OPENAI_API_KEY")
        )

    @property
    def supports_tools(self) -> bool:
        return True

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

    async def complete(
        self, session_id: str, messages: list[dict], tools: list[dict] | None = None
    ) -> ChatCompletionResult:
        from openai import OpenAIError

        kwargs = dict(
            model=self._settings.model_name,
            max_completion_tokens=self._settings.max_tokens,
            messages=messages,
        )
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = "auto"

        try:
            response = await self._client.chat.completions.create(**kwargs)
        except OpenAIError as exc:
            raise ChatServiceError(str(exc)) from exc

        msg = response.choices[0].message
        tool_calls = [
            ToolCall(
                id=tc.id,
                name=tc.function.name,
                arguments=json.loads(tc.function.arguments or "{}"),
            )
            for tc in (msg.tool_calls or [])
        ]
        return ChatCompletionResult(
            text=msg.content,
            tool_calls=tool_calls,
            raw_assistant_message=msg.model_dump(exclude_none=True),
        )
