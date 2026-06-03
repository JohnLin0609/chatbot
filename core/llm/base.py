"""Provider-agnostic chat service interface."""

from abc import ABC, abstractmethod

from core.config import Settings


class ChatServiceError(Exception):
    """Raised when the upstream LLM call fails (bad key, network, etc.)."""


def _require(value: str, name: str) -> str:
    if not value:
        raise ChatServiceError(f"{name} is required for the selected provider")
    return value


class ChatService(ABC):
    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    @abstractmethod
    async def generate_reply(self, session_id: str, messages: list[dict]) -> str:
        """Return an assistant reply for a prepared message list.

        `messages` is an OpenAI-style list of {"role", "content"} dicts already
        assembled by core.memory.context_builder (system + summary + recent
        turns + current user). Providers translate it to their own SDK shape.
        """
