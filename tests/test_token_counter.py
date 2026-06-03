"""TokenCounter tests."""

from core.tokens.counter import TokenCounter


def test_count_text_nonzero():
    c = TokenCounter()
    assert c.count_text("hello world") > 0
    assert c.count_text("") == 0


def test_count_turn_includes_overhead():
    c = TokenCounter()
    bare = c.count_text("hi")
    turn = c.count_turn({"role": "user", "content": "hi"})
    assert turn > bare  # per-turn overhead added


def test_count_turns_sums():
    c = TokenCounter()
    turns = [
        {"role": "user", "content": "abc"},
        {"role": "assistant", "content": "def"},
    ]
    assert c.count_turns(turns) == c.count_turn(turns[0]) + c.count_turn(turns[1])


def test_fallback_when_encoder_missing():
    c = TokenCounter()
    c._encoder = None  # simulate offline
    assert c.count_text("a" * 40) == 10  # len//4
