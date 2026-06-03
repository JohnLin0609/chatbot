"""Assemble the LLM context from hot-store state (summary + recent turns)."""

from core.config import Settings
from core.llm.messages import build_messages


def build_context(
    settings: Settings,
    summary: dict | None,
    turns: list[dict],
    user_text: str,
) -> list[dict]:
    """Build the message list: system + running summary + recent N turns + user.

    `turns` is a flat list of {role, content} message dicts (2 per turn). Only
    the most recent `recent_turns` turns are fed to the model; older history
    lives in the running summary and Postgres.
    """
    recent = turns[-(2 * settings.recent_turns):] if settings.recent_turns else []
    recent = [{"role": t["role"], "content": t["content"]} for t in recent]
    summary_text = summary.get("text") if summary else None
    return build_messages(settings.system_prompt, summary_text, recent, user_text)
