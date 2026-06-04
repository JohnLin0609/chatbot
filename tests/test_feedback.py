"""FeedbackStore: insert / toggle-off / flip + summary aggregation."""

from core.feedback.store import FeedbackStore
from core.persistence import repository as repo


async def test_rate_insert_toggle_flip(sessionmaker):
    store = FeedbackStore(sessionmaker)
    # insert 👍
    assert await store.rate(100, "7", 1) == 1
    # same rating again toggles off
    assert await store.rate(100, "7", 1) == 0
    # insert again, then flip to 👎
    assert await store.rate(100, "7", 1) == 1
    assert await store.rate(100, "7", -1) == -1
    # a different user is independent
    assert await store.rate(100, "8", 1) == 1


async def test_get_for_user(sessionmaker):
    store = FeedbackStore(sessionmaker)
    await store.rate(1, "7", 1)
    await store.rate(2, "7", -1)
    await store.rate(2, "8", 1)
    got = await store.get_for_user([1, 2, 3], "7")
    assert got == {1: 1, 2: -1}


async def test_summary_counts_and_recent_negatives(sessionmaker):
    store = FeedbackStore(sessionmaker)
    async with sessionmaker() as db:
        s = await repo.ensure_session(db, "web:7:c1", "web", "7:c1")
        a1 = await repo.append_message(db, s.id, "assistant", "bad answer")
        a2 = await repo.append_message(db, s.id, "assistant", "good answer")
        await db.commit()
        bad_id, good_id = a1.id, a2.id

    await store.rate(good_id, "7", 1)
    await store.rate(bad_id, "7", -1)
    await store.rate(bad_id, "8", -1)

    summary = await store.summary()
    assert summary["up"] == 1
    assert summary["down"] == 2
    contents = {n["content"] for n in summary["recent_negative"]}
    assert "bad answer" in contents
    assert "good answer" not in contents
