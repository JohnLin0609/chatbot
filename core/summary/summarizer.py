"""Running-summary maintenance: decide when to summarise and do it.

The summariser is DB-agnostic: it updates the Redis hot store and returns the
new summary dict (or None). The pipeline is responsible for persisting the
returned summary to Postgres.
"""

from core.config import Settings
from core.llm.base import ChatService
from core.memory.hot_store import HotStore


def _estimate_tokens(turns: list[dict]) -> int:
    # Rough heuristic: ~4 chars per token. Good enough for a threshold.
    chars = sum(len(t.get("content", "")) for t in turns)
    return chars // 4


def _should_summarize(settings: Settings, turns: list[dict]) -> bool:
    turn_count = len(turns) // 2
    if turn_count >= settings.summary_trigger_turns:
        return True
    if (
        settings.summary_trigger_tokens > 0
        and _estimate_tokens(turns) >= settings.summary_trigger_tokens
    ):
        return True
    return False


def _format_turns(turns: list[dict]) -> str:
    return "\n".join(f"{t['role']}: {t['content']}" for t in turns)


class Summarizer:
    def __init__(
        self, settings: Settings, chat_service: ChatService, hot_store: HotStore
    ) -> None:
        self._settings = settings
        self._chat = chat_service
        self._hot = hot_store

    async def maybe_summarize(
        self, session_key: str, summary: dict | None, turns: list[dict]
    ) -> dict | None:
        """If over threshold, fold older turns into the summary.

        Updates the hot store (summary + trimmed turns) and returns the new
        summary dict, or None when no summarisation was needed.
        """
        if not _should_summarize(self._settings, turns):
            return None

        keep_messages = 2 * self._settings.recent_turns
        to_summarize = turns[:-keep_messages] if keep_messages else turns
        kept = turns[-keep_messages:] if keep_messages else []
        if not to_summarize:
            return None

        prev_text = summary.get("text") if summary else None
        prompt = (
            f"Existing summary:\n{prev_text or '(none)'}\n\n"
            f"New turns to fold in:\n{_format_turns(to_summarize)}\n\n"
            "Produce the updated running summary."
        )
        messages = [
            {"role": "system", "content": self._settings.summary_system_prompt},
            {"role": "user", "content": prompt},
        ]
        new_text = await self._chat.generate_reply(session_key, messages)

        prev_count = summary.get("turn_count", 0) if summary else 0
        new_summary = {
            "text": new_text,
            "turn_count": prev_count + len(to_summarize) // 2,
            "covers_through_message_id": None,
        }
        await self._hot.set_summary(session_key, new_summary)
        await self._hot.replace_turns(session_key, kept)
        return new_summary
