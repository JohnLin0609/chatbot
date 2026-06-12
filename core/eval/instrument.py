"""InstrumentedChatService: wraps a ChatService to record a lightweight llm_call
row (call_type, model, token estimates, latency) for every call, without touching
providers or call sites. Duck-types ChatService (generate_reply/complete/
supports_tools). Logging is fire-and-forget and never affects the wrapped call."""

import logging
import time

from core.background import spawn

log = logging.getLogger("eval.instrument")


class InstrumentedChatService:
    def __init__(self, inner, logger, call_type: str) -> None:
        self._inner = inner
        self._logger = logger
        self._call_type = call_type

    @property
    def supports_tools(self) -> bool:
        return self._inner.supports_tools

    async def generate_reply(self, session_id: str, messages: list[dict]) -> str:
        t0 = time.perf_counter()
        ok, err, text = True, None, ""
        try:
            text = await self._inner.generate_reply(session_id, messages)
            return text
        except Exception as e:  # noqa: BLE001 — re-raised after logging
            ok, err = False, str(e)
            raise
        finally:
            self._fire(session_id, messages, text, (time.perf_counter() - t0) * 1000, ok, err)

    async def complete(self, session_id: str, messages: list[dict], tools=None):
        t0 = time.perf_counter()
        ok, err, result = True, None, None
        try:
            result = await self._inner.complete(session_id, messages, tools)
            return result
        except Exception as e:  # noqa: BLE001
            ok, err = False, str(e)
            raise
        finally:
            text = (getattr(result, "text", "") or "") if result else ""
            self._fire(session_id, messages, text, (time.perf_counter() - t0) * 1000, ok, err)

    def _fire(self, session_id, messages, text, latency_ms, ok, err) -> None:
        try:
            spawn(self._logger.log_call(
                self._call_type,
                messages=messages,
                output_text=text,
                latency_ms=latency_ms,
                ok=ok,
                error=err,
                session_key=session_id,
            ))
        except RuntimeError:
            # no running event loop (shouldn't happen in the async worker) — skip
            log.debug("no running loop for log_call (%s)", self._call_type)
