"""Summarizer trigger + folding tests."""

from core.memory.hot_store import HotStore
from core.summary.summarizer import Summarizer
from tests.conftest import FakeChat


def _turns(n):
    out = []
    for i in range(n):
        out.append({"role": "user", "content": f"u{i}"})
        out.append({"role": "assistant", "content": f"a{i}"})
    return out


async def test_no_summary_below_threshold(settings, redis):
    hot = HotStore(redis, settings)
    summ = Summarizer(settings, FakeChat("S"), hot)
    # threshold is 3 turns; provide 2
    result = await summ.maybe_summarize("cli:c1", None, _turns(2))
    assert result is None


async def test_summarizes_over_threshold(settings, redis):
    hot = HotStore(redis, settings)
    chat = FakeChat("running summary")
    summ = Summarizer(settings, chat, hot)
    turns = _turns(3)  # == trigger
    result = await summ.maybe_summarize("cli:c1", None, turns)

    assert result is not None
    assert result["text"] == "running summary"
    # recent_turns=2 kept, so 1 turn folded -> turn_count 1
    assert result["turn_count"] == 1
    # hot store now holds only the kept recent turns
    _s, kept = await hot.load("cli:c1")
    assert len(kept) == 2 * settings.recent_turns


async def test_existing_summary_count_accumulates(settings, redis):
    hot = HotStore(redis, settings)
    summ = Summarizer(settings, FakeChat("merged"), hot)
    result = await summ.maybe_summarize(
        "cli:c1", {"text": "old", "turn_count": 5}, _turns(3)
    )
    assert result["turn_count"] == 6  # 5 + 1 folded
