"""Eval logging: persist a rich trace per main-reply turn plus lightweight
per-call telemetry. All writes are best-effort — a logging failure must never
break or delay the reply (callers fire these via asyncio.create_task)."""

import logging

from sqlalchemy.ext.asyncio import async_sessionmaker

from core.config import Settings
from core.eval.schemas import RetrievalTrace
from core.persistence.models import EvalRetrievedChunk, EvalTrace, LlmCall
from core.tokens.counter import TokenCounter

log = logging.getLogger("eval.logger")


class NullEvalLogger:
    """No-op logger used when eval logging is disabled."""

    async def log_call(self, *args, **kwargs) -> None:
        return None

    async def log_trace(self, *args, **kwargs) -> None:
        return None


class EvalLogger:
    def __init__(
        self,
        sessionmaker: async_sessionmaker,
        token_counter: TokenCounter,
        settings: Settings,
    ) -> None:
        self._sm = sessionmaker
        self._counter = token_counter
        self._settings = settings

    @property
    def _model(self) -> str:
        return self._settings.model_name

    @property
    def _provider(self) -> str:
        return getattr(self._settings.provider, "value", str(self._settings.provider))

    async def log_call(
        self,
        call_type: str,
        *,
        messages: list[dict] | None = None,
        output_text: str = "",
        latency_ms: float | None = None,
        ok: bool = True,
        error: str | None = None,
        session_key: str | None = None,
        user_key: str | None = None,
    ) -> None:
        try:
            prompt_tokens = self._counter.count_turns(messages or [])
            completion_tokens = self._counter.count_text(output_text or "")
            async with self._sm() as db:
                db.add(LlmCall(
                    call_type=call_type,
                    model=self._model,
                    provider=self._provider,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    latency_ms=latency_ms,
                    ok=ok,
                    error=error,
                    session_key=session_key,
                    user_key=user_key,
                ))
                await db.commit()
        except Exception:  # noqa: BLE001 — telemetry must never break the turn
            log.warning("log_call failed (%s)", call_type, exc_info=True)

    async def log_trace(
        self,
        *,
        event_id: str | None,
        correlation_id: str | None,
        session_db_id: int | None,
        session_key: str | None,
        user_id: str | None,
        conversation_id: str | None,
        query: str | None,
        retrieval: RetrievalTrace | None,
        system_prompt: str | None,
        knowledge_text: str | None,
        messages: list[dict] | None,
        reply_text: str | None,
        reply_message_id: int | None,
        tool_calls_count: int = 0,
        retrieval_latency_ms: float | None = None,
        generation_latency_ms: float | None = None,
    ) -> None:
        try:
            # token estimates first (before any body-nulling)
            prompt_tokens = self._counter.count_turns(messages or [])
            completion_tokens = self._counter.count_text(reply_text or "")
            total_latency = None
            if retrieval_latency_ms is not None or generation_latency_ms is not None:
                total_latency = (retrieval_latency_ms or 0.0) + (generation_latency_ms or 0.0)

            keep_bodies = self._settings.eval_log_message_bodies
            cap = self._settings.eval_chunk_text_max

            async with self._sm() as db:
                trace = EvalTrace(
                    event_id=event_id,
                    correlation_id=correlation_id,
                    session_db_id=session_db_id,
                    session_key=session_key,
                    user_id=user_id,
                    conversation_id=conversation_id,
                    query=query if keep_bodies else None,
                    rag_tier=retrieval.tier if retrieval else None,
                    reranked=bool(retrieval and retrieval.reranked),
                    system_prompt=system_prompt if keep_bodies else None,
                    knowledge_text=knowledge_text if keep_bodies else None,
                    messages=messages if keep_bodies else None,
                    reply_text=reply_text if keep_bodies else None,
                    reply_message_id=reply_message_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                    model=self._model,
                    provider=self._provider,
                    tool_calls_count=tool_calls_count,
                    retrieval_latency_ms=retrieval_latency_ms,
                    generation_latency_ms=generation_latency_ms,
                    total_latency_ms=total_latency,
                )
                db.add(trace)
                await db.flush()  # populate trace.id

                if retrieval:
                    for c in retrieval.candidates:
                        text = c.chunk_text
                        if not keep_bodies:
                            text = None
                        elif text is not None and cap and len(text) > cap:
                            text = text[:cap]
                        db.add(EvalRetrievedChunk(
                            trace_id=trace.id,
                            doc_id=c.doc_id,
                            chunk_index=c.chunk_index,
                            point_id=c.point_id,
                            title=c.title,
                            chunk_text=text,
                            fused_score=c.fused_score,
                            fused_rank=c.fused_rank,
                            rerank_score=c.rerank_score,
                            final_rank=c.final_rank,
                            included=c.included,
                        ))
                await db.commit()
        except Exception:  # noqa: BLE001 — never break the turn
            log.warning("log_trace failed", exc_info=True)
