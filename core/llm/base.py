"""Provider-agnostic chat service interface."""

from abc import ABC, abstractmethod

from core.config import Settings
from core.tools.schemas import ChatCompletionResult


class ChatServiceError(Exception):
    """Raised when the upstream LLM call fails (bad key, network, etc.)."""


def _require(value: str, name: str) -> str:
    if not value:
        raise ChatServiceError(f"{name} is required for the selected provider")
    return value


class ChatService(ABC):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @property
    def supports_tools(self) -> bool:
        """Whether this provider implements tool-calling in `complete`."""
        return False

    @abstractmethod
    async def generate_reply(self, session_id: str, messages: list[dict]) -> str:
        """Return an assistant reply for a prepared message list.

        `messages` is an OpenAI-style list of {"role", "content"} dicts already
        assembled by core.memory.context_builder (system + summary + recent
        turns + current user). Providers translate it to their own SDK shape.
        """

    async def complete(
        self, session_id: str, messages: list[dict], tools: list[dict] | None = None
    ) -> ChatCompletionResult:
        """Lower-level completion that can return tool calls.

        Default implementation ignores tools and returns plain text via
        generate_reply — so providers without tool support degrade gracefully.
        OpenAI overrides this to actually emit/parse tool calls.
        """
        text = await self.generate_reply(session_id, messages)
        return ChatCompletionResult(
            text=text,
            tool_calls=[],
            raw_assistant_message={"role": "assistant", "content": text},
        )
