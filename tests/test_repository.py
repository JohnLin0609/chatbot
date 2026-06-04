"""Repository round-trips on in-memory sqlite."""

from core.persistence import repository as repo
from core.persistence.models import MessageFeedback, Summary


async def test_ensure_session_is_idempotent(sessionmaker):
    async with sessionmaker() as db:
        s1 = await repo.ensure_session(db, "cli:c1", "cli", "c1")
        await db.commit()
        first_id = s1.id
    async with sessionmaker() as db:
        s2 = await repo.ensure_session(db, "cli:c1", "cli", "c1")
        await db.commit()
        assert s2.id == first_id


async def test_append_and_load_recent_chronological(sessionmaker):
    async with sessionmaker() as db:
        s = await repo.ensure_session(db, "cli:c1", "cli", "c1")
        await repo.append_message(db, s.id, "user", "u1")
        await repo.append_message(db, s.id, "assistant", "a1")
        await repo.append_message(db, s.id, "user", "u2")
        await db.commit()
        recent = await repo.load_recent(db, s.id, limit=2)
        # most recent 2, oldest-first
        assert [m.content for m in recent] == ["a1", "u2"]


async def test_save_and_get_latest_summary(sessionmaker):
    async with sessionmaker() as db:
        s = await repo.ensure_session(db, "cli:c1", "cli", "c1")
        await repo.save_summary(db, s.id, "first", turn_count=1)
        await repo.save_summary(db, s.id, "second", turn_count=2)
        await db.commit()
        latest = await repo.get_latest_summary(db, s.id)
        assert latest.summary_text == "second"


async def test_delete_session_by_key_cascades(sessionmaker):
    from sqlalchemy import select

    async with sessionmaker() as db:
        s = await repo.ensure_session(db, "web:7:c1", "web", "7:c1")
        u = await repo.append_message(db, s.id, "user", "hi", user_id="7")
        a = await repo.append_message(db, s.id, "assistant", "yo")
        await repo.save_summary(db, s.id, "sum", turn_count=1,
                                covers_through_message_id=a.id)
        db.add(MessageFeedback(message_id=a.id, user_id="7", rating=1))
        await db.commit()

        deleted = await repo.delete_session_by_key(db, "web:7:c1")
        await db.commit()
        assert deleted is True

        # session, its messages, summaries, and feedback are all gone
        assert await repo.load_recent(db, s.id, limit=10) == []
        assert (await db.execute(select(Summary))).scalars().all() == []
        assert (await db.execute(select(MessageFeedback))).scalars().all() == []
        _ = u  # user msg also removed via cascade


async def test_delete_session_by_key_missing_is_noop(sessionmaker):
    async with sessionmaker() as db:
        assert await repo.delete_session_by_key(db, "web:9:none") is False


async def test_app_setting_crud(sessionmaker):
    async with sessionmaker() as db:
        assert await repo.get_app_setting(db, "system_prompt") is None
        await repo.upsert_app_setting(db, "system_prompt", "be a pirate")
        await db.commit()
        assert await repo.get_app_setting(db, "system_prompt") == "be a pirate"
        await repo.upsert_app_setting(db, "system_prompt", "be a poet")
        await db.commit()
        assert await repo.get_app_setting(db, "system_prompt") == "be a poet"
        await repo.delete_app_setting(db, "system_prompt")
        await db.commit()
        assert await repo.get_app_setting(db, "system_prompt") is None
