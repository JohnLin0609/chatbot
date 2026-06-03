"""FactExtractor tests (mock LLM)."""

import json
from datetime import datetime, timezone

from core.facts.extractor import FactExtractor, _extract_json
from core.facts.schema import FactEntry, UserMemoryDocument
from core.tokens.counter import TokenCounter
from tests.conftest import make_settings

C = TokenCounter()
NOW = datetime(2026, 6, 3, tzinfo=timezone.utc)


class ReplyChat:
    def __init__(self, reply):
        self._reply = reply

    async def generate_reply(self, key, messages):
        return self._reply


def _extractor(reply):
    return FactExtractor(make_settings(), ReplyChat(reply), C)


def test_extract_json_tolerant():
    assert _extract_json('{"a":1}') == {"a": 1}
    assert _extract_json('blah\n{"a": 1}\ntrailing') == {"a": 1}
    assert _extract_json("not json") == {}


async def test_single_fact_added():
    delta = json.dumps({"facts": [{"key": "name", "value": "小明", "confidence": 0.9}]})
    doc = await _extractor(delta).extract("line:U1", UserMemoryDocument.empty("line:U1"), [])
    assert doc.facts["name"].value == "小明"
    assert doc.facts["name"].confidence == 0.9


async def test_single_replace_moves_old_to_superseded():
    doc = UserMemoryDocument.empty("line:U1")
    doc.facts["occupation"] = FactEntry(value="前端工程師", created_at=NOW, updated_at=NOW)
    delta = json.dumps({"facts": [{"key": "occupation", "value": "後端工程師"}]})
    out = await _extractor(delta).extract("line:U1", doc, [])
    assert out.facts["occupation"].value == "後端工程師"
    assert any(s.key == "occupation" and s.value == "前端工程師" for s in out.superseded)
    # created_at preserved from the original
    assert out.facts["occupation"].created_at == NOW


async def test_multi_fact_dedupe_append():
    doc = UserMemoryDocument.empty("line:U1")
    doc.facts["langs"] = FactEntry(cardinality="multi", value=["zh"], created_at=NOW, updated_at=NOW)
    delta = json.dumps({"facts": [{"key": "langs", "value": ["zh", "en"], "cardinality": "multi"}]})
    out = await _extractor(delta).extract("line:U1", doc, [])
    assert out.facts["langs"].value == ["zh", "en"]


async def test_retire():
    doc = UserMemoryDocument.empty("line:U1")
    doc.facts["location"] = FactEntry(value="高雄", created_at=NOW, updated_at=NOW)
    delta = json.dumps({"retire": [{"key": "location", "reason": "moved"}]})
    out = await _extractor(delta).extract("line:U1", doc, [])
    assert "location" not in out.facts
    assert out.superseded[0].key == "location"


async def test_facts_and_retire_same_key_keeps_new_value():
    # Self-contradictory delta: set a new value AND retire the same key.
    # The new value must win; created_at preserved; new value NOT superseded.
    doc = UserMemoryDocument.empty("line:U1")
    doc.facts["profession"] = FactEntry(value="後端工程師", created_at=NOW, updated_at=NOW)
    delta = json.dumps({
        "facts": [{"key": "profession", "value": "資料工程師"}],
        "retire": [{"key": "profession", "reason": "changed jobs"}],
    })
    out = await _extractor(delta).extract("line:U1", doc, [])
    assert out.facts["profession"].value == "資料工程師"
    assert out.facts["profession"].created_at == NOW  # preserved
    superseded_values = [s.value for s in out.superseded]
    assert "後端工程師" in superseded_values   # old value archived
    assert "資料工程師" not in superseded_values  # new value NOT retired


async def test_rolling_summary_updated():
    delta = json.dumps({"rolling_summary": "User is a backend engineer."})
    out = await _extractor(delta).extract("line:U1", UserMemoryDocument.empty("line:U1"), [])
    assert out.rolling_summary == "User is a backend engineer."
    assert out.summary_updated_at is not None


async def test_confidence_default():
    delta = json.dumps({"facts": [{"key": "name", "value": "小明"}]})
    out = await _extractor(delta).extract("line:U1", UserMemoryDocument.empty("line:U1"), [])
    assert out.facts["name"].confidence == 0.5


async def test_should_extract_threshold(sessionmaker):
    from core.persistence import repository as repo

    ext = FactExtractor(make_settings(fact_extraction_tokens=1000), ReplyChat("{}"), C)
    async with sessionmaker() as db:
        s = await repo.ensure_session(db, "line:c1", "line", "c1")
        await repo.append_message(db, s.id, "user", "hi", user_id="U1")
        await db.commit()
        enough, pending = await ext.should_extract(db, "U1", None)
        assert enough is False  # one short message << 1000 tokens
        assert len(pending) == 1
