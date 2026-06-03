"""Repository round-trips on in-memory sqlite."""

from core.persistence import repository as repo


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
