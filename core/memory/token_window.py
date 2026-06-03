"""Whole-turn token windowing.

Splits a flat message list (oldest-first) into the recent turns that fit under a
token budget and the older turns that overflow. Splitting is always at whole-turn
boundaries — a turn is never cut in half.
"""

from core.tokens.counter import TokenCounter


def _group_turns(messages: list[dict]) -> list[list[dict]]:
    """Group a flat message list into turns (a 'user' starts a new turn)."""
    turns: list[list[dict]] = []
    for msg in messages:
        if msg["role"] == "user" or not turns:
            turns.append([msg])
        else:
            turns[-1].append(msg)
    return turns


def select_window(
    counter: TokenCounter, messages: list[dict], window_tokens: int
) -> tuple[list[dict], list[dict]]:
    """Return (in_window, overflow) as flat message lists, both oldest-first.

    Includes the most recent whole turns whose cumulative tokens stay within
    `window_tokens`. Always keeps at least the most recent turn, even if that
    single turn already exceeds the budget.
    """
    if not messages:
        return [], []

    turns = _group_turns(messages)
    kept_turns: list[list[dict]] = []
    used = 0
    for turn in reversed(turns):
        turn_tokens = counter.count_turns(turn)
        if kept_turns and used + turn_tokens > window_tokens:
            break
        kept_turns.append(turn)
        used += turn_tokens

    kept_turns.reverse()
    kept_count = len(kept_turns)
    overflow_turns = turns[: len(turns) - kept_count]

    in_window = [m for turn in kept_turns for m in turn]
    overflow = [m for turn in overflow_turns for m in turn]
    return in_window, overflow
