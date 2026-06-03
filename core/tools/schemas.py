"""Data types for the tool-calling framework."""

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # avoid import cycles; these are only type hints
    from core.config import Settings
    from core.rag.embeddings import EmbeddingService
    from core.rag.vector_store import QdrantVectorStore
    from core.web.brave import BraveSearchService


@dataclass
class ToolContext:
    """Dependencies + per-request info handed to a tool handler."""

    settings: "Settings"
    embedding_service: "EmbeddingService"
    vector_store: "QdrantVectorStore"
    session_id: str
    user_key: str
    channel_id: str
    # Present only when a Brave API key is configured (see web_search tool).
    web_search_service: "BraveSearchService | None" = None


# A handler takes (parsed arguments, context) and returns text for the LLM.
ToolHandler = Callable[[dict, ToolContext], Awaitable[str]]


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    parameters: dict  # JSON Schema for the function arguments
    handler: ToolHandler
    # Optional registration gate: register this tool only when requires(settings)
    # is truthy (e.g. an API key is present). None = always available.
    requires: Callable[["Settings"], bool] | None = field(default=None, compare=False)

    def to_openai(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ChatCompletionResult:
    """Outcome of one LLM completion: final text and/or requested tool calls."""

    text: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    # The assistant message kept verbatim (incl. tool_calls) to stack back into
    # the message list — OpenAI requires this exact shape on the next call.
    raw_assistant_message: dict[str, Any] = field(default_factory=dict)
