"""Summarizer fold_overflow tests."""

from core.summary.summarizer import Summarizer
from tests.conftest import FakeChat, make_settings


def _turns(n):
    out = []
    for i in range(n):
        out.append({"role": "user", "content": f"u{i}"})
        out.append({"role": "assistant", "content": f"a{i}"})
    return out


async def test_no_overflow_returns_none():
    summ = Summarizer(make_settings(), FakeChat("S"))
    assert await summ.fold_overflow("cli:c1", None, []) is None


async def test_folds_overflow_into_summary():
    summ = Summarizer(make_settings(), FakeChat("channel summary"))
    result = await summ.fold_overflow("cli:c1", None, _turns(2), covers_through_message_id=42)
    assert result["text"] == "channel summary"
    assert result["turn_count"] == 2
    assert result["covers_through_message_id"] == 42


async def test_turn_count_accumulates():
    summ = Summarizer(make_settings(), FakeChat("merged"))
    result = await summ.fold_overflow(
        "cli:c1", {"text": "old", "turn_count": 5}, _turns(3)
    )
    assert result["turn_count"] == 8  # 5 + 3 folded
