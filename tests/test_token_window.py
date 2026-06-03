"""select_window tests — whole-turn boundaries."""

from core.memory.token_window import select_window
from core.tokens.counter import TokenCounter

C = TokenCounter()


def _turns(n):
    out = []
    for i in range(n):
        out.append({"role": "user", "content": f"user message {i}"})
        out.append({"role": "assistant", "content": f"assistant reply {i}"})
    return out


def test_empty():
    assert select_window(C, [], 100) == ([], [])


def test_all_fit():
    msgs = _turns(2)
    in_window, overflow = select_window(C, msgs, 10_000)
    assert in_window == msgs
    assert overflow == []


def test_overflow_oldest_first_and_whole_turns():
    msgs = _turns(5)
    # budget for ~2 turns
    per_turn = C.count_turns(msgs[:2])
    in_window, overflow = select_window(C, msgs, per_turn * 2 + 1)
    # whole turns only -> even number of messages
    assert len(in_window) % 2 == 0
    assert len(overflow) % 2 == 0
    assert in_window and overflow
    # overflow is the older messages, in_window the newer
    assert overflow[0]["content"] == "user message 0"
    assert in_window[-1]["content"] == "assistant reply 4"
    assert in_window + overflow != msgs  # reordered, but union preserved
    assert overflow + in_window == msgs


def test_keeps_at_least_latest_turn_even_if_over_budget():
    msgs = _turns(3)
    in_window, overflow = select_window(C, msgs, 1)  # tiny budget
    assert in_window == msgs[-2:]  # last whole turn kept
    assert overflow == msgs[:-2]
