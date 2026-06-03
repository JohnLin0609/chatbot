"""UserMemoryStore tests (fakeredis + sqlite)."""

from datetime import datetime, timezone

from core.facts.schema import FactEntry, UserMemoryDocument
from core.facts.store import UserMemoryStore


def _doc(user_key="line:U1"):
    now = datetime.now(timezone.utc)
    doc = UserMemoryDocument.empty(user_key)
    doc.facts["name"] = FactEntry(value="小明", created_at=now, updated_at=now)
    return doc


async def test_load_empty_then_save_roundtrip(settings, redis, sessionmaker):
    store = UserMemoryStore(redis, settings)
    async with sessionmaker() as db:
        doc = await store.load(db, "line:U1")
        assert doc.facts == {}
        await store.save(db, "line:U1", _doc())
        await db.commit()
    # fresh redis miss -> read-through from PG
    await redis.flushall()
    async with sessionmaker() as db:
        doc2 = await store.load(db, "line:U1")
        assert doc2.facts["name"].value == "小明"


async def test_redis_mirror_hit(settings, redis, sessionmaker):
    store = UserMemoryStore(redis, settings)
    async with sessionmaker() as db:
        await store.save(db, "line:U1", _doc())
        await db.commit()
    # without touching PG again, mirror should serve it
    assert await redis.get(store._key("line:U1")) is not None


async def test_cursor_get_set(settings, redis, sessionmaker):
    store = UserMemoryStore(redis, settings)
    async with sessionmaker() as db:
        assert await store.get_cursor(db, "line:U1") is None
        await store.save(db, "line:U1", _doc())
        await store.set_cursor(db, "line:U1", 42)
        await db.commit()
        assert await store.get_cursor(db, "line:U1") == 42


async def test_bump_last_used(settings, redis, sessionmaker):
    store = UserMemoryStore(redis, settings)
    async with sessionmaker() as db:
        await store.save(db, "line:U1", _doc())
        await db.commit()
        await store.bump_last_used(db, "line:U1", ["name", "missing"])
        await db.commit()
        doc = await store.load(db, "line:U1")
        assert doc.facts["name"].last_used_at is not None
