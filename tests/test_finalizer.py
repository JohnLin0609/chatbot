"""Session finalizer: tier-2 fold + tier-3 force-extract + sweep selection."""

import json
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from sqlalchemy import func, select

from core.facts.extractor import FactExtractor
from core.facts.store import UserMemoryStore
from core.persistence.models import Message, Session, Summary, UserMemory
from core.session.finalizer import finalize_session, sweep_idle_sessions
from core.summary.summarizer import Summarizer
from core.tokens.counter import TokenCounter
from tests.conftest import make_settings

OLD = datetime(2020, 1, 1, tzinfo=timezone.utc)


class FinalizerChat:
    """Returns fact JSON for the extraction prompt, a summary for the summary
    prompt, else an echo."""

    supports_tools = False

    def __init__(self, settings):
        self._fact = settings.fact_system_prompt
        self._channel = settings.channel_summary_system_prompt

    async def generate_reply(self, key, messages):
        sys = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
        if sys == self._fact:
            return json.dumps({
                "facts": [{"key": "name", "value": "小明", "confidence": 0.9}],
                "rolling_summary": "User is 小明.",
            })
        if sys == self._channel:
            return "channel summary text"
        return "echo"


def _deps(settings, redis, sessionmaker):
    chat = FinalizerChat(make_settings())
    counter = TokenCounter(settings.tiktoken_encoding)
    return SimpleNamespace(
        settings=settings,
        sessionmaker=sessionmaker,
        summarizer=Summarizer(settings, chat),
        fact_extractor=FactExtractor(settings, chat, counter),
        user_memory_store=UserMemoryStore(redis, settings),
    )


async def _seed(sessionmaker, *, session_key="web:1:c1", platform="web",
                channel="1:c1", user_id="1", n_turns=2, last_active=OLD,
                finalized_at=None) -> int:
    async with sessionmaker() as db:
        sess = Session(session_key=session_key, platform=platform,
                       channel_id=channel, last_active_at=last_active,
                       finalized_at=finalized_at)
        db.add(sess)
        await db.flush()
        for i in range(n_turns):
            db.add(Message(session_id=sess.id, role="user",
                           content=f"message {i}", user_id=user_id))
            db.add(Message(session_id=sess.id, role="assistant", content="ok"))
        await db.commit()
        return sess.id


async def test_finalize_folds_tier2_summary(redis, sessionmaker):
    s = make_settings()
    sid = await _seed(sessionmaker)
    deps = _deps(s, redis, sessionmaker)
    async with sessionmaker() as db:
        session = await db.get(Session, sid)
        await finalize_session(deps, db, session)
        await db.commit()
    async with sessionmaker() as db:
        summaries = (await db.execute(select(Summary).where(Summary.session_id == sid))).scalars().all()
    assert len(summaries) == 1
    assert summaries[0].summary_text == "channel summary text"
    assert summaries[0].covers_through_message_id is not None


async def test_finalize_force_extracts_tier3(redis, sessionmaker):
    # huge threshold: normal extraction would NOT fire, but finalize forces it
    s = make_settings(fact_extraction_tokens=10_000_000)
    sid = await _seed(sessionmaker)
    deps = _deps(s, redis, sessionmaker)
    async with sessionmaker() as db:
        await finalize_session(deps, db, await db.get(Session, sid))
        await db.commit()
    async with sessionmaker() as db:
        row = (await db.execute(select(UserMemory).where(UserMemory.user_key == "web:1"))).scalar_one_or_none()
    assert row is not None
    assert "name" in row.document["facts"]
    assert row.last_extracted_message_id is not None


async def test_finalize_sets_finalized_at_and_second_is_noop(redis, sessionmaker):
    s = make_settings()
    sid = await _seed(sessionmaker)
    deps = _deps(s, redis, sessionmaker)
    async with sessionmaker() as db:
        session = await db.get(Session, sid)
        await finalize_session(deps, db, session)
        await db.commit()
        assert session.finalized_at is not None
    # second finalize: no new messages -> no new summary
    async with sessionmaker() as db:
        await finalize_session(deps, db, await db.get(Session, sid))
        await db.commit()
    async with sessionmaker() as db:
        count = (await db.execute(select(func.count()).select_from(Summary).where(Summary.session_id == sid))).scalar()
    assert count == 1  # not re-folded


async def test_sweep_selects_idle_unfinalized_only(redis, sessionmaker):
    s = make_settings()
    idle = await _seed(sessionmaker, session_key="web:1:idle", channel="1:idle", last_active=OLD)
    recent = await _seed(sessionmaker, session_key="web:2:recent", channel="2:recent",
                         user_id="2", last_active=datetime.now(timezone.utc))
    n = await sweep_idle_sessions(_deps(s, redis, sessionmaker))
    assert n == 1
    async with sessionmaker() as db:
        assert (await db.get(Session, idle)).finalized_at is not None
        assert (await db.get(Session, recent)).finalized_at is None


async def test_already_finalized_session_is_skipped(redis, sessionmaker):
    s = make_settings()
    # finalized AFTER its last activity -> already done, not eligible
    await _seed(sessionmaker, last_active=datetime(2020, 1, 1, tzinfo=timezone.utc),
                finalized_at=datetime(2020, 6, 1, tzinfo=timezone.utc))
    assert await sweep_idle_sessions(_deps(s, redis, sessionmaker)) == 0


async def test_reactivated_session_is_eligible_again(redis, sessionmaker):
    s = make_settings()
    # active again AFTER a prior finalization (both in the past -> still idle)
    sid = await _seed(sessionmaker,
                      finalized_at=datetime(2020, 1, 1, tzinfo=timezone.utc),
                      last_active=datetime(2020, 6, 1, tzinfo=timezone.utc))
    deps = _deps(s, redis, sessionmaker)
    assert await sweep_idle_sessions(deps) == 1  # last_active > finalized -> eligible
    async with sessionmaker() as db:
        # now finalized_at >= last_active -> no longer eligible
        assert (await db.get(Session, sid)).finalized_at is not None
    assert await sweep_idle_sessions(deps) == 0
