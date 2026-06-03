"""UserMemory repository + facts schema tests (sqlite)."""

from datetime import datetime, timezone

from core.facts.schema import FactEntry, UserMemoryDocument
from core.persistence import repository as repo


def test_document_empty_and_roundtrip():
    doc = UserMemoryDocument.empty("line:U1")
    assert doc.user_id == "line:U1"
    assert doc.facts == {}
    now = datetime.now(timezone.utc)
    doc.facts["name"] = FactEntry(value="小明", created_at=now, updated_at=now)
    j = doc.to_json()
    back = UserMemoryDocument.model_validate(j)
    assert back.facts["name"].value == "小明"


async def test_upsert_and_get_user_memory(sessionmaker):
    async with sessionmaker() as db:
        await repo.upsert_user_memory(db, "line:U1", {"a": 1}, last_extracted_message_id=5)
        await db.commit()
    async with sessionmaker() as db:
        row = await repo.get_user_memory(db, "line:U1")
        assert row.document == {"a": 1}
        assert row.last_extracted_message_id == 5
        # update keeps row, advances cursor
        await repo.upsert_user_memory(db, "line:U1", {"a": 2}, last_extracted_message_id=9)
        await db.commit()
        row2 = await repo.get_user_memory(db, "line:U1")
        assert row2.document == {"a": 2}
        assert row2.last_extracted_message_id == 9


async def test_load_messages_after_filters_user_and_cursor(sessionmaker):
    async with sessionmaker() as db:
        s = await repo.ensure_session(db, "line:c1", "line", "c1")
        await repo.append_message(db, s.id, "user", "m1", user_id="U1")
        await repo.append_message(db, s.id, "assistant", "r1")  # user_id None
        await repo.append_message(db, s.id, "user", "m2", user_id="U2")
        await repo.append_message(db, s.id, "user", "m3", user_id="U1")
        await db.commit()

        u1_all = await repo.load_messages_after(db, "U1", None)
        assert [m.content for m in u1_all] == ["m1", "m3"]

        after_first = await repo.load_messages_after(db, "U1", u1_all[0].id)
        assert [m.content for m in after_first] == ["m3"]
