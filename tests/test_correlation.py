"""OutboundWaiter: correlation matching, timeouts, cleanup, reader resilience.

These pin the contract the HTTP gateway relies on: register BEFORE publishing
inbound, then wait; the reader resolves matched futures and acks everything.
"""

import asyncio
import time
import uuid

import pytest
import pytest_asyncio

from interfaces.correlation import OutboundWaiter
from shared import redis_client as rc
from shared.events import OutboundEvent, to_stream_fields
from tests.conftest import make_settings

S = make_settings(reply_timeout_seconds=0.2)


def _outbound(cid: str, text: str = "reply") -> OutboundEvent:
    return OutboundEvent(
        event_id=str(uuid.uuid4()), in_reply_to=str(uuid.uuid4()),
        platform="web", channel_id="c1", session_id="web:c1",
        correlation_id=cid, text=text, timestamp=time.time(),
    )


async def _publish(redis, event: OutboundEvent) -> None:
    await rc.publish(redis, S.outbound_stream, to_stream_fields(event))


@pytest_asyncio.fixture
async def waiter(redis):
    w = OutboundWaiter(redis, S, S.http_consumer_group, "test-consumer")
    await w.start()
    yield w
    await w.stop()


async def test_register_then_publish_resolves(waiter, redis):
    waiter.register("c1")
    await _publish(redis, _outbound("c1", "hello back"))
    event = await waiter.wait("c1")
    assert event.text == "hello back"
    assert waiter._pending == {}  # cleaned up after resolution


async def test_wait_times_out_and_cleans_up(waiter):
    waiter.register("never")
    with pytest.raises(asyncio.TimeoutError):
        await waiter.wait("never")
    assert waiter._pending == {}  # the finally pop ran


async def test_unmatched_outbound_is_acked_and_harmless(waiter, redis):
    await _publish(redis, _outbound("nobody-waits"))
    # The reader consumes + acks it without a registered future...
    waiter.register("c2")
    await _publish(redis, _outbound("c2"))
    event = await waiter.wait("c2")  # ...and keeps serving matched events
    assert event.correlation_id == "c2"
    pending = await redis.xpending(S.outbound_stream, S.http_consumer_group)
    assert pending["pending"] == 0  # everything acked, matched or not


async def test_reply_arriving_before_wait_still_resolves(waiter, redis):
    waiter.register("early")
    await _publish(redis, _outbound("early"))
    await asyncio.sleep(0.05)  # reader resolves the future before wait() runs
    event = await waiter.wait("early")
    assert event.correlation_id == "early"


async def test_publish_before_register_is_lost(waiter, redis):
    """Pins the gateway contract: register BEFORE publishing inbound. A reply
    consumed with no registered future is dropped (acked), so a late wait
    times out instead of receiving it."""
    await _publish(redis, _outbound("too-soon"))
    await asyncio.sleep(0.05)
    with pytest.raises(asyncio.TimeoutError):
        await waiter.wait("too-soon")


async def test_concurrent_waiters_each_get_their_event(waiter, redis):
    waiter.register("a")
    waiter.register("b")
    await _publish(redis, _outbound("b", "reply-b"))  # reverse order
    await _publish(redis, _outbound("a", "reply-a"))
    got_a, got_b = await asyncio.gather(waiter.wait("a"), waiter.wait("b"))
    assert got_a.text == "reply-a"
    assert got_b.text == "reply-b"


async def test_reader_survives_redis_error(waiter, redis, monkeypatch):
    real = rc.read_group
    failed = False

    async def flaky(*args, **kwargs):
        nonlocal failed
        if not failed:
            failed = True
            raise ConnectionError("redis hiccup")
        return await real(*args, **kwargs)

    monkeypatch.setattr(rc, "read_group", flaky)
    waiter.register("after-error")
    await _publish(redis, _outbound("after-error"))
    # Reader logs the error, sleeps 1s, then resumes and resolves the future.
    event = await asyncio.wait_for(waiter._pending["after-error"], timeout=3)
    assert event.correlation_id == "after-error"
    assert failed


async def test_stop_cancels_reader(redis):
    w = OutboundWaiter(redis, S, S.http_consumer_group, "stopper")
    await w.start()
    task = w._task
    await w.stop()
    assert task.cancelled() or task.done()


async def test_register_binds_future_to_running_loop(waiter):
    future = waiter.register("loop-check")
    assert future.get_loop() is asyncio.get_running_loop()
