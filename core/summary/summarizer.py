"""Per-channel running summary: fold overflow turns into a short summary.

Driven by the token window — whenever turns overflow the context window, the
overflow is folded into a concise (~150 token) running summary. This replaces
the old turn-count batch trigger.
"""

from core.config import Settings
from core.llm.base import ChatService


def _format_turns(turns: list[dict]) -> str:
    return "\n".join(f"{t['role']}: {t['content']}" for t in turns)


class Summarizer:
    def __init__(self, settings: Settings, chat_service: ChatService) -> None:
        self._settings = settings
        self._chat = chat_service

    async def fold_overflow(
        self,
        session_key: str,
        summary: dict | None,
        overflow_turns: list[dict],
        covers_through_message_id: int | None = None,
    ) -> dict | None:
        """Fold overflow turns into the running summary. Returns the new summary
        dict, or None if there was nothing to fold."""
        if not overflow_turns:
            return None

        prev_text = summary.get("text") if summary else None
        prompt = (
            f"Existing summary:\n{prev_text or '(none)'}\n\n"
            f"New turns to fold in:\n{_format_turns(overflow_turns)}\n\n"
            "Produce the updated running summary (<=150 tokens)."
        )
        messages = [
            {"role": "system", "content": self._settings.channel_summary_system_prompt},
            {"role": "user", "content": prompt},
        ]
        new_text = await self._chat.generate_reply(session_key, messages)

        prev_count = summary.get("turn_count", 0) if summary else 0
        return {
            "text": new_text,
            "turn_count": prev_count + len(overflow_turns) // 2,
            "covers_through_message_id": covers_through_message_id,
        }
