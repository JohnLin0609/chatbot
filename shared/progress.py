"""Best-effort progress events: the worker broadcasts what it's doing during a
single reply (LLM thinking, tool start/end) so an adapter can reflect live status
(e.g. Discord reactions).

Decoupled from the durable outbound stream on purpose: this is ephemeral status
over Redis pub/sub. A dropped message just means a momentarily stale indicator;
the final reply always arrives via the outbound stream.
"""

import logging
import time
from typing import Protocol

from pydantic import BaseModel

from redis.asyncio import Redis

from core.config import Settings

log = logging.getLogger("progress")

# Progress kinds.
THINKING = "thinking"
TOOL_START = "tool_start"
TOOL_END = "tool_end"


class ProgressEvent(BaseModel):
    correlation_id: str
    kind: str  # THINKING | TOOL_START | TOOL_END
    tool: str | None = None
    timestamp: float


class ProgressEmitter(Protocol):
    async def emit(
        self, correlation_id: str, kind: str, tool: str | None = None
    ) -> None: ...


class NullProgressEmitter:
    """No-op emitter — the default everywhere except the live worker."""

    async def emit(
        self, correlation_id: str, kind: str, tool: str | None = None
    ) -> None:
        return None


class RedisProgressEmitter:
    """Publish progress to a Redis pub/sub channel. Fire-and-forget."""

    def __init__(self, redis: Redis, settings: Settings) -> None:
        self._redis = redis
        self._channel = settings.progress_channel

    async def emit(
        self, correlation_id: str, kind: str, tool: str | None = None
    ) -> None:
        event = ProgressEvent(
            correlation_id=correlation_id, kind=kind, tool=tool, timestamp=time.time()
        )
        try:
            await self._redis.publish(self._channel, event.model_dump_json())
        except Exception:  # noqa: BLE001 — progress is best-effort, never break a reply
            log.debug("progress publish failed", exc_info=True)


def progress_from_message(data: str | bytes) -> ProgressEvent:
    """Parse a pub/sub message payload into a ProgressEvent."""
    if isinstance(data, bytes):
        data = data.decode()
    return ProgressEvent.model_validate_json(data)
