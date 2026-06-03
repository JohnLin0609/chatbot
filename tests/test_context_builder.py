"""Context assembly tests."""

from core.memory.context_builder import build_context
from tests.conftest import make_settings


def test_minimal_system_and_user():
    msgs = build_context(
        make_settings(), channel_summary_text="", personal_memory_text="",
        window_turns=[], user_text="hello",
    )
    assert msgs[0]["role"] == "system"
    assert msgs[-1] == {"role": "user", "content": "hello"}
    assert len(msgs) == 2


def test_injects_channel_and_personal():
    msgs = build_context(
        make_settings(),
        channel_summary_text="chan sum",
        personal_memory_text="occupation: 後端工程師",
        window_turns=[{"role": "user", "content": "a"}, {"role": "assistant", "content": "b"}],
        user_text="now",
    )
    systems = [m["content"] for m in msgs if m["role"] == "system"]
    assert any("Channel summary" in s and "chan sum" in s for s in systems)
    assert any("current speaker" in s and "後端工程師" in s for s in systems)
    # window turns present, current user last
    contents = [m["content"] for m in msgs]
    assert "a" in contents and "b" in contents
    assert msgs[-1] == {"role": "user", "content": "now"}


def test_omits_empty_blocks():
    msgs = build_context(
        make_settings(), channel_summary_text="", personal_memory_text="x: y",
        window_turns=[], user_text="hi",
    )
    systems = [m["content"] for m in msgs if m["role"] == "system"]
    assert not any("Channel summary" in s for s in systems)
    assert any("current speaker" in s for s in systems)
