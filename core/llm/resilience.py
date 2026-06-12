"""ResilientChatService: timeout + bounded retry around any provider.

Every upstream call gets a hard `llm_timeout_seconds` deadline so a hung
provider can never pin a worker slot. Timeouts and ChatServiceErrors (network,
5xx — providers normalise their SDK errors to it) are retried up to
`llm_max_retries` times with exponential backoff, then re-raised as a
ChatServiceError. Wrapped once in build_chat_service so the worker, judge and
golden runner all inherit it.
"""

import asyncio
import logging
from typing import Awaitable, Callable, TypeVar

from core.config import Settings
from core.llm.base import ChatService, ChatServiceError
from core.tools.schemas import ChatCompletionResult

log = logging.getLogger("llm.resilience")

T = TypeVar("T")


class ResilientChatService(ChatService):
    def __init__(self, inner: ChatService, settings: Settings) -> None:
        super().__init__(settings)
        self._inner = inner

    @property
    def supports_tools(self) -> bool:
        return self._inner.supports_tools

    async def generate_reply(self, session_id: str, messages: list[dict]) -> str:
        return await self._call(
            lambda: self._inner.generate_reply(session_id, messages)
        )

    async def complete(
        self, session_id: str, messages: list[dict], tools: list[dict] | None = None
    ) -> ChatCompletionResult:
        return await self._call(
            lambda: self._inner.complete(session_id, messages, tools)
        )

    async def _call(self, thunk: Callable[[], Awaitable[T]]) -> T:
        attempts = self._settings.llm_max_retries + 1
        last_exc: Exception | None = None
        for attempt in range(attempts):
            try:
                return await asyncio.wait_for(
                    thunk(), timeout=self._settings.llm_timeout_seconds
                )
            except asyncio.TimeoutError as exc:
                last_exc = exc
                log.warning("LLM call timed out after %.0fs (attempt %d/%d)",
                            self._settings.llm_timeout_seconds, attempt + 1, attempts)
            except ChatServiceError as exc:
                last_exc = exc
                log.warning("LLM call failed (attempt %d/%d): %s",
                            attempt + 1, attempts, exc)
            if attempt + 1 < attempts:
                await asyncio.sleep(
                    self._settings.llm_retry_backoff_seconds * (2 ** attempt)
                )
        if isinstance(last_exc, asyncio.TimeoutError):
            raise ChatServiceError(
                f"LLM call timed out after {attempts} attempt(s)"
            ) from last_exc
        raise ChatServiceError(str(last_exc)) from last_exc
