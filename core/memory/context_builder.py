"""Assemble the final LLM message list from all memory tiers.

Order: system persona → channel summary (tier-2) → speaker personal memory
(tier-3) → in-window turns (tier-1) → current user message.
"""

from core.config import Settings


def build_context(
    settings: Settings,
    *,
    channel_summary_text: str,
    personal_memory_text: str,
    window_turns: list[dict],
    user_text: str,
) -> list[dict]:
    messages: list[dict] = [{"role": "system", "content": settings.system_prompt}]

    if channel_summary_text:
        messages.append(
            {"role": "system", "content": f"Channel summary:\n{channel_summary_text}"}
        )
    if personal_memory_text:
        messages.append(
            {
                "role": "system",
                "content": f"About the current speaker:\n{personal_memory_text}",
            }
        )

    for turn in window_turns:
        messages.append({"role": turn["role"], "content": turn["content"]})

    messages.append({"role": "user", "content": user_text})
    return messages
