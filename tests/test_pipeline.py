"""End-to-end core pipeline tests (fakeredis + sqlite + fake LLM)."""

import time
import uuid

from sqlalchemy import func, select

from core.llm.base import ChatServiceError
from core.memory.hot_store import HotStore
from core.persistence.models import Message, Session, Summary
from core.pipeline import PipelineDeps, handle_inbound
from core.summary.summarizer import Summarizer
from shared.events import InboundEvent, make_session_id
from tests.conftest import FakeChat


def _inbound(text: str) -> InboundEvent:
    return InboundEvent(
        event_id=str(uuid.uuid4()), platform="cli", channel_id="c1",
        session_id=make_session_id("cli", "c1"), user_id="u1", text=text,
        message_id=str(uuid.uuid4()), correlation_id=f"corr-{text}",
        timestamp=time.time(),
    )


def _deps(settings, redis, sessionmaker, chat):
    hot = HotStore(redis, settings)
    return PipelineDeps(
        settings=settings, hot_store=hot, sessionmaker=sessionmaker,
        chat_service=chat, summarizer=Summarizer(settings, chat, hot),
    )


async def test_reply_and_correlation_passthrough(settings, redis, sessionmaker):
    deps = _deps(settings, redis, sessionmaker, FakeChat())
    out = await handle_inbound(_inbound("hello"), deps)
    assert out.status == "ok"
    assert out.text == "reply-to:hello"
    assert out.correlation_id == "corr-hello"
    assert out.session_id == "cli:c1"


async def test_persists_messages(settings, redis, sessionmaker):
    deps = _deps(settings, redis, sessionmaker, FakeChat())
    await handle_inbound(_inbound("hi"), deps)
    async with sessionmaker() as db:
        count = (await db.execute(select(func.count()).select_from(Message))).scalar()
        sessions = (await db.execute(select(Session))).scalars().all()
    assert count == 2  # user + assistant
    assert [s.session_key for s in sessions] == ["cli:c1"]


async def test_memory_carries_across_turns(settings, redis, sessionmaker):
    deps = _deps(settings, redis, sessionmaker, FakeChat())
    await handle_inbound(_inbound("first"), deps)
    out = await handle_inbound(_inbound("second"), deps)
    # the second call's context must contain the first turn
    last_context = deps.chat_service.calls[-1]
    contents = [m["content"] for m in last_context]
    assert "first" in contents
    assert out.text == "reply-to:second"


async def test_summary_triggers_and_persists(settings, redis, sessionmaker):
    deps = _deps(settings, redis, sessionmaker, FakeChat("SUMMARY"))
    for t in ["a", "b", "c", "d"]:  # trigger=3
        await handle_inbound(_inbound(t), deps)
    async with sessionmaker() as db:
        summaries = (await db.execute(select(func.count()).select_from(Summary))).scalar()
    assert summaries >= 1


async def test_llm_error_returns_error_outbound_without_persisting(
    settings, redis, sessionmaker
):
    class BoomChat:
        async def generate_reply(self, session_id, messages):
            raise ChatServiceError("upstream down")

    deps = _deps(settings, redis, sessionmaker, BoomChat())
    out = await handle_inbound(_inbound("hi"), deps)
    assert out.status == "error"
    assert "upstream down" in out.error
    async with sessionmaker() as db:
        count = (await db.execute(select(func.count()).select_from(Message))).scalar()
    assert count == 0  # nothing persisted on error


async def test_cold_backfill_from_postgres(settings, redis, sessionmaker):
    # First turn populates Postgres, then wipe the hot store to force backfill.
    deps = _deps(settings, redis, sessionmaker, FakeChat())
    await handle_inbound(_inbound("remember"), deps)
    await redis.flushall()

    out = await handle_inbound(_inbound("again"), deps)
    last_context = deps.chat_service.calls[-1]
    contents = [m["content"] for m in last_context]
    assert "remember" in contents  # backfilled from durable history
    assert out.status == "ok"
