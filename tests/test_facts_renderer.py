"""Renderer tests: slimming, ranking, budget."""

from datetime import datetime, timedelta, timezone

from core.facts.renderer import render_channel_summary, render_personal_memory
from core.facts.schema import FactEntry, UserMemoryDocument
from core.tokens.counter import TokenCounter
from tests.conftest import make_settings

C = TokenCounter()
NOW = datetime(2026, 6, 3, tzinfo=timezone.utc)


def _entry(value, confidence=0.9, days_ago=0, **kw):
    t = NOW - timedelta(days=days_ago)
    return FactEntry(value=value, confidence=confidence, created_at=t, updated_at=t,
                     last_used_at=t, **kw)


def test_slims_to_key_value():
    doc = UserMemoryDocument.empty("line:U1")
    doc.facts["occupation"] = _entry("後端工程師", confidence=0.9)
    text, used = render_personal_memory(doc, C, make_settings(), now=NOW)
    assert "occupation: 後端工程師" in text
    assert "confidence" not in text and "0.9" not in text
    assert used == ["occupation"]


def test_multi_value_joined():
    doc = UserMemoryDocument.empty("line:U1")
    doc.facts["langs"] = _entry(["zh", "en"], **{})
    doc.facts["langs"].cardinality = "multi"
    text, _ = render_personal_memory(doc, C, make_settings(), now=NOW)
    assert "langs: zh, en" in text


def test_rolling_summary_first():
    doc = UserMemoryDocument.empty("line:U1")
    doc.rolling_summary = "User is a backend engineer."
    doc.facts["x"] = _entry("y")
    text, _ = render_personal_memory(doc, C, make_settings(), now=NOW)
    assert text.splitlines()[0] == "User is a backend engineer."


def test_budget_drops_low_priority():
    s = make_settings(personal_memory_token_cap=12)  # room for ~1-2 short facts
    doc = UserMemoryDocument.empty("line:U1")
    doc.facts["high"] = _entry("aaa", confidence=0.95, days_ago=0)
    doc.facts["low"] = _entry("bbb", confidence=0.1, days_ago=400)
    text, used = render_personal_memory(doc, C, s, now=NOW)
    assert "high" in used
    # high-priority fact wins the limited budget
    assert used[0] == "high"


def test_channel_summary_truncates():
    long = " ".join(f"Sentence {i}." for i in range(50))
    out = render_channel_summary({"text": long}, C, cap=10)
    assert C.count_text(out) <= 12  # within cap (+ rounding)
    assert out.startswith("Sentence 0.")


def test_channel_summary_passthrough_when_short():
    assert render_channel_summary({"text": "short"}, C, cap=100) == "short"
    assert render_channel_summary(None, C, cap=100) == ""
