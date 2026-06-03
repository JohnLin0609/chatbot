"""Context assembly tests."""

from core.memory.context_builder import build_context
from tests.conftest import make_settings


def _turns(n):
    out = []
    for i in range(n):
        out.append({"role": "user", "content": f"u{i}"})
        out.append({"role": "assistant", "content": f"a{i}"})
    return out


def test_includes_system_and_user():
    s = make_settings(recent_turns=2)
    msgs = build_context(s, None, [], "hello")
    assert msgs[0]["role"] == "system"
    assert msgs[-1] == {"role": "user", "content": "hello"}


def test_summary_added_as_second_system():
    s = make_settings(recent_turns=2)
    msgs = build_context(s, {"text": "running summary"}, [], "hi")
    systems = [m for m in msgs if m["role"] == "system"]
    assert len(systems) == 2
    assert "running summary" in systems[1]["content"]


def test_only_recent_turns_fed():
    s = make_settings(recent_turns=2)
    msgs = build_context(s, None, _turns(5), "now")
    # 1 system + 2 turns (4 messages) + current user
    non_system = [m for m in msgs if m["role"] != "system"]
    assert len(non_system) == 5  # 4 recent + current
    assert non_system[0]["content"] == "u3"  # oldest kept is turn 3
