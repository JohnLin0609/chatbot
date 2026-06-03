"""Google Gemini provider."""

from core.config import Settings
from core.llm.base import ChatService, ChatServiceError, _require
from core.llm.messages import split_system


class GeminiChatService(ChatService):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        from google import genai

        self._client = genai.Client(
            api_key=_require(settings.gemini_api_key, "GEMINI_API_KEY")
        )

    async def generate_reply(self, session_id: str, messages: list[dict]) -> str:
        from google.genai import types
        from google.genai.errors import APIError

        system_text, turns = split_system(messages)
        # Gemini uses 'model' for the assistant role and a 'contents' list.
        contents = [
            types.Content(
                role="model" if t["role"] == "assistant" else "user",
                parts=[types.Part(text=t["content"])],
            )
            for t in turns
        ]
        try:
            response = await self._client.aio.models.generate_content(
                model=self._settings.model_name,
                contents=contents,
                config=types.GenerateContentConfig(
                    system_instruction=system_text,
                    max_output_tokens=self._settings.max_tokens,
                ),
            )
        except APIError as exc:
            raise ChatServiceError(str(exc)) from exc

        return response.text or ""
