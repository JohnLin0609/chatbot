"""End-to-end core pipeline tests (fakeredis + sqlite + fake LLM)."""

import json
import time
import uuid

from sqlalchemy import func, select

from core.facts.extractor import FactExtractor
from core.facts.store import UserMemoryStore
from core.llm.base import ChatServiceError
from core.memory.hot_store import HotStore
from core.persistence.models import Message, Session, UserMemory
from core.pipeline import PipelineDeps, handle_inbound
from core.summary.summarizer import Summarizer
from core.tokens.counter import TokenCounter
from shared.events import InboundEvent, make_session_id
from tests.conftest import FakeChat, make_settings


def _inbound(text: str, user_id="U1", channel="c1") -> InboundEvent:
    return InboundEvent(
        event_id=str(uuid.uuid4()), platform="line", channel_id=channel,
        session_id=make_session_id("line", channel), user_id=user_id, text=text,
        message_id=str(uuid.uuid4()), correlation_id=f"corr-{text}", timestamp=time.time(),
    )


def _deps(settings, redis, sessionmaker, chat):
    counter = TokenCounter(settings.tiktoken_encoding)
    hot = HotStore(redis, settings)
    store = UserMemoryStore(redis, settings)
    return PipelineDeps(
        settings=settings, hot_store=hot, sessionmaker=sessionmaker, chat_service=chat,
        summarizer=Summarizer(settings, chat), token_counter=counter,
        user_memory_store=store, fact_extractor=FactExtractor(settings, chat, counter),
    )


class FactAwareChat:
    """Returns fact JSON for the extraction prompt, summaries for the summary
    prompt, and an echo otherwise."""

    def __init__(self, settings):
        self._fact_prompt = settings.fact_system_prompt
        self._channel_prompt = settings.channel_summary_system_prompt
        self.calls = []

    async def generate_reply(self, key, messages):
        self.calls.append(messages)
        sys = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
        if sys == self._fact_prompt:
            return json.dumps({
                "facts": [{"key": "name", "value": "小明", "confidence": 0.9}],
                "rolling_summary": "User is 小明.",
            })
        if sys == self._channel_prompt:
            return "channel summary"
        last_user = [m for m in messages if m["role"] == "user"][-1]["content"]
        return f"reply-to:{last_user}"


# --------------------------------------------------------------- basic
async def test_reply_and_correlation_passthrough(redis, sessionmaker):
    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    out = await handle_inbound(_inbound("hello"), _deps(s, redis, sessionmaker, FakeChat()))
    assert out.status == "ok"
    assert out.text == "reply-to:hello"
    assert out.correlation_id == "corr-hello"


async def test_persists_messages(redis, sessionmaker):
    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    await handle_inbound(_inbound("hi"), _deps(s, redis, sessionmaker, FakeChat()))
    async with sessionmaker() as db:
        count = (await db.execute(select(func.count()).select_from(Message))).scalar()
        sessions = (await db.execute(select(Session))).scalars().all()
    assert count == 2
    assert [x.session_key for x in sessions] == ["line:c1"]


async def test_memory_carries_across_turns(redis, sessionmaker):
    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    chat = FakeChat()
    deps = _deps(s, redis, sessionmaker, chat)
    await handle_inbound(_inbound("first"), deps)
    out = await handle_inbound(_inbound("second"), deps)
    second_call = [c for c in chat.calls if c[-1]["content"] == "second"][-1]
    assert "first" in [m["content"] for m in second_call]
    assert out.text == "reply-to:second"


async def test_llm_error_returns_error_without_persisting(redis, sessionmaker):
    class BoomChat:
        async def generate_reply(self, key, messages):
            raise ChatServiceError("upstream down")

    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    out = await handle_inbound(_inbound("hi"), _deps(s, redis, sessionmaker, BoomChat()))
    assert out.status == "error"
    async with sessionmaker() as db:
        count = (await db.execute(select(func.count()).select_from(Message))).scalar()
    assert count == 0


async def test_cold_backfill_from_postgres(redis, sessionmaker):
    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    deps = _deps(s, redis, sessionmaker, FakeChat())
    await handle_inbound(_inbound("remember"), deps)
    await redis.flushall()
    out = await handle_inbound(_inbound("again"), deps)
    last_main = [c for c in deps.chat_service.calls if c[-1]["content"] == "again"][-1]
    assert "remember" in [m["content"] for m in last_main]
    assert out.status == "ok"


# --------------------------------------------------------------- tier-2
async def test_overflow_folds_channel_summary(redis, sessionmaker):
    from core.persistence.models import Summary

    s = make_settings(context_window_tokens=20, fact_extraction_tokens=100_000)
    deps = _deps(s, redis, sessionmaker, FactAwareChat(make_settings()))
    for t in ["aaa", "bbb", "ccc", "ddd", "eee", "fff"]:
        await handle_inbound(_inbound(t), deps)
    async with sessionmaker() as db:
        summaries = (await db.execute(select(func.count()).select_from(Summary))).scalar()
    assert summaries >= 1  # window overflowed -> channel summary folded


# --------------------------------------------------------------- tier-3
async def test_fact_extraction_populates_user_memory(redis, sessionmaker):
    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=20)
    deps = _deps(s, redis, sessionmaker, FactAwareChat(make_settings()))
    for t in ["hi there friend", "how are you doing today", "tell me a story"]:
        await handle_inbound(_inbound(t), deps)
    async with sessionmaker() as db:
        row = (await db.execute(select(UserMemory).where(UserMemory.user_key == "line:U1"))).scalar_one_or_none()
    assert row is not None
    assert "name" in row.document["facts"]
    assert row.last_extracted_message_id is not None  # cursor advanced


async def test_invariant_messages_preserved_when_window_shrinks(redis, sessionmaker):
    # tier-3 disabled (huge threshold) so cursor never advances; window tiny.
    s = make_settings(context_window_tokens=20, fact_extraction_tokens=10_000_000)
    deps = _deps(s, redis, sessionmaker, FactAwareChat(make_settings()))
    n = 6
    for i in range(n):
        await handle_inbound(_inbound(f"message number {i}"), deps)
    async with sessionmaker() as db:
        msg_count = (await db.execute(select(func.count()).select_from(Message))).scalar()
        row = (await db.execute(select(UserMemory).where(UserMemory.user_key == "line:U1"))).scalar_one_or_none()
    assert msg_count == 2 * n  # all turns durably preserved
    # hot window shrank below the full history
    _summary, turns = await deps.hot_store.load("line:c1")
    assert len(turns) < 2 * n
    # cursor never advanced (no extraction)
    assert row is None or row.last_extracted_message_id is None


async def test_fact_extraction_async_helper(redis, sessionmaker):
    # Drive turns with extraction disabled, then run the async background helper
    # directly (it opens its own session — same path the async branch fires).
    from core.pipeline import _extract_facts_async

    base = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000_000)
    deps = _deps(base, redis, sessionmaker, FactAwareChat(make_settings()))
    for t in ["hi there friend", "how are you doing today"]:
        await handle_inbound(_inbound(t), deps)

    low = make_settings(fact_extraction_tokens=5)
    deps2 = _deps(low, redis, sessionmaker, FactAwareChat(make_settings()))
    await _extract_facts_async(deps2, "line:U1", "U1")

    async with sessionmaker() as db:
        row = (await db.execute(select(UserMemory).where(UserMemory.user_key == "line:U1"))).scalar_one_or_none()
    assert row is not None and "name" in row.document["facts"]
    assert row.last_extracted_message_id is not None
