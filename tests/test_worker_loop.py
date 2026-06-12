"""Worker consume loop: ack/leave-pending/reclaim semantics + sweeper resilience.

Pins the retry contract: LLM errors (ChatServiceError) get an error outbound
and are acked; unexpected crashes leave the message pending so another worker
(or the next pass) can reclaim it.
"""

import asyncio
import time
import uuid

from core.llm.base import ChatServiceError
from interfaces.worker import _sweeper, run_once
from shared import redis_client as rc
from shared.events import (
    InboundEvent,
    make_session_id,
    outbound_from_stream_fields,
    to_stream_fields,
)
from tests.conftest import FakeChat, make_settings
from tests.factories import build_deps

S = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)


class CrashingChat(FakeChat):
    """Unexpected failure (not a ChatServiceError) — simulates a worker bug."""

    async def generate_reply(self, session_id, messages):
        raise RuntimeError("boom")


class LlmErrorChat(FakeChat):
    """Upstream LLM failure — the pipeline converts this to an error reply."""

    async def generate_reply(self, session_id, messages):
        raise ChatServiceError("rate limited")


def _publish_inbound(redis, text: str = "hello", cid: str | None = None):
    event = InboundEvent(
        event_id=str(uuid.uuid4()), platform="line", channel_id="c1",
        session_id=make_session_id("line", "c1"), user_id="U1", text=text,
        message_id=str(uuid.uuid4()), correlation_id=cid or str(uuid.uuid4()),
        timestamp=time.time(),
    )
    return rc.publish(redis, S.inbound_stream, to_stream_fields(event)), event


async def _setup(redis):
    await rc.ensure_group(redis, S.inbound_stream, S.core_consumer_group)


async def _outbound_events(redis):
    entries = await redis.xrange(S.outbound_stream)
    return [outbound_from_stream_fields(fields) for _, fields in entries]


async def _pending_count(redis) -> int:
    info = await redis.xpending(S.inbound_stream, S.core_consumer_group)
    return info["pending"]


async def test_happy_path_publishes_outbound_and_acks(redis, sessionmaker):
    await _setup(redis)
    coro, inbound = _publish_inbound(redis, "hello")
    await coro
    deps = build_deps(S, redis, sessionmaker, FakeChat())

    attempted = await run_once(redis, deps, S, "w1", block_ms=10)

    assert attempted == 1
    events = await _outbound_events(redis)
    assert len(events) == 1
    assert events[0].correlation_id == inbound.correlation_id
    assert events[0].status == "ok"
    assert events[0].text == "reply-to:hello"
    assert await _pending_count(redis) == 0  # acked


async def test_unexpected_crash_leaves_message_pending(redis, sessionmaker):
    await _setup(redis)
    coro, _ = _publish_inbound(redis)
    await coro
    deps = build_deps(S, redis, sessionmaker, CrashingChat())

    await run_once(redis, deps, S, "w1", block_ms=10)  # must not raise

    assert await _outbound_events(redis) == []  # no reply published
    assert await _pending_count(redis) == 1  # left for retry


async def test_pending_message_is_reclaimed_and_retried(redis, sessionmaker):
    await _setup(redis)
    coro, inbound = _publish_inbound(redis, "retry me")
    await coro
    crashing = build_deps(S, redis, sessionmaker, CrashingChat())
    await run_once(redis, crashing, S, "w1", block_ms=10)
    assert await _pending_count(redis) == 1

    # A healthy worker reclaims the abandoned message and finishes the job.
    healthy = build_deps(S, redis, sessionmaker, FakeChat())
    await run_once(redis, healthy, S, "w2", autoclaim_min_idle_ms=0, block_ms=10)

    events = await _outbound_events(redis)
    assert [e.correlation_id for e in events] == [inbound.correlation_id]
    assert events[0].status == "ok"
    assert await _pending_count(redis) == 0


async def test_llm_error_publishes_error_outbound_and_acks(redis, sessionmaker):
    await _setup(redis)
    coro, inbound = _publish_inbound(redis)
    await coro
    deps = build_deps(S, redis, sessionmaker, LlmErrorChat())

    await run_once(redis, deps, S, "w1", block_ms=10)

    events = await _outbound_events(redis)
    assert len(events) == 1
    assert events[0].status == "error"
    assert "rate limited" in events[0].error
    assert events[0].correlation_id == inbound.correlation_id
    assert await _pending_count(redis) == 0  # replied-to, not retried


async def test_malformed_message_left_pending_loop_survives(redis, sessionmaker):
    await _setup(redis)
    await rc.publish(redis, S.inbound_stream, {"data": "not-json{"})
    deps = build_deps(S, redis, sessionmaker, FakeChat())

    attempted = await run_once(redis, deps, S, "w1", block_ms=10)

    assert attempted == 1
    assert await _outbound_events(redis) == []
    assert await _pending_count(redis) == 1

    # The loop keeps serving well-formed messages afterwards.
    coro, inbound = _publish_inbound(redis, "still alive")
    await coro
    await run_once(redis, deps, S, "w1", block_ms=10)
    events = await _outbound_events(redis)
    assert [e.correlation_id for e in events] == [inbound.correlation_id]


async def test_sweeper_survives_exceptions_and_keeps_sweeping(
    redis, sessionmaker, monkeypatch
):
    import core.session.finalizer as finalizer

    calls = 0

    async def flaky_sweep(deps):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("sweep blew up")
        return 1

    monkeypatch.setattr(finalizer, "sweep_idle_sessions", flaky_sweep)
    settings = make_settings(session_sweep_interval_seconds=0)
    deps = build_deps(settings, redis, sessionmaker, FakeChat())

    task = asyncio.create_task(_sweeper(deps, settings))
    while calls < 3:
        await asyncio.sleep(0.01)
    task.cancel()

    assert calls >= 3  # survived the first-iteration crash and kept going
