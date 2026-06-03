"""Ollama (local) provider."""

from core.config import Settings
from core.llm.base import ChatService, ChatServiceError


class OllamaChatService(ChatService):
    def __init__(self, settings: Settings) -> None:
        super().__init__(settings)
        from ollama import AsyncClient

        self._client = AsyncClient(host=settings.ollama_host)

    async def generate_reply(self, session_id: str, messages: list[dict]) -> str:
        from ollama import ResponseError

        try:
            response = await self._client.chat(
                model=self._settings.model_name,
                messages=messages,
                options={"num_predict": self._settings.max_tokens},
            )
        except (ResponseError, ConnectionError) as exc:
            raise ChatServiceError(str(exc)) from exc

        return response["message"]["content"]
