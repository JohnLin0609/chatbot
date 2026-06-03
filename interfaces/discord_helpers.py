"""Pure helpers for the Discord adapter — no `discord` import, so they unit-test
without the gateway. The client in `discord_app.py` wires these to discord.py.
"""

import re
import time
import uuid

from shared.events import InboundEvent, make_session_id
from shared.progress import THINKING, TOOL_END, TOOL_START

# --- reaction status UX -------------------------------------------------------
# A single current-phase reaction on the user's message; it advances and
# self-cleans, leaving only ✅ (or ❌) at the end.
PHASE_EMOJI = {
    "received": "👀",
    "thinking": "🧠",
    "done": "✅",
    "error": "❌",
}
TOOL_EMOJI = {
    "web_search": "🌐",
    "search_knowledge": "🔎",
}
DEFAULT_TOOL_EMOJI = "🛠️"

DISCORD_MSG_LIMIT = 2000


def reaction_for(phase: str, tool: str | None = None) -> str:
    """Emoji for a status phase. phase='tool' uses the per-tool map."""
    if phase == "tool":
        return TOOL_EMOJI.get(tool or "", DEFAULT_TOOL_EMOJI)
    return PHASE_EMOJI[phase]


def emoji_for_progress(kind: str, tool: str | None = None) -> str:
    """Map a worker ProgressEvent to the reaction the adapter should show."""
    if kind == TOOL_START:
        return reaction_for("tool", tool)
    # THINKING or TOOL_END -> the model is (back to) thinking.
    return reaction_for("thinking")


# --- trigger / content --------------------------------------------------------
def parse_allowed_guilds(csv: str) -> set[str]:
    """Parse the CSV allowlist; empty string -> empty set (= allow all)."""
    return {g.strip() for g in (csv or "").split(",") if g.strip()}


def should_handle(
    *,
    is_dm: bool,
    is_bot: bool,
    mentioned: bool,
    guild_id: str | None,
    allowed_guilds: set[str],
) -> bool:
    """Reply to every DM, and to guild messages only when @mentioned (and the
    guild is allowed). Never to bots/self."""
    if is_bot:
        return False
    if is_dm:
        return True
    if not mentioned:
        return False
    if allowed_guilds and guild_id not in allowed_guilds:
        return False
    return True


def clean_content(text: str, bot_user_id: int | str) -> str:
    """Strip the bot's own mention (`<@id>` / `<@!id>`) from message text."""
    return re.sub(rf"<@!?{bot_user_id}>", "", text or "").strip()


def chunk_message(text: str, limit: int = DISCORD_MSG_LIMIT) -> list[str]:
    """Split a reply into Discord-sized chunks (<= limit chars)."""
    if not text:
        return []
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def build_inbound(
    *,
    text: str,
    channel_id: str,
    user_id: str,
    message_id: str,
    correlation_id: str,
) -> InboundEvent:
    """Map a Discord message's fields to an InboundEvent."""
    return InboundEvent(
        event_id=str(uuid.uuid4()),
        platform="discord",
        channel_id=channel_id,
        session_id=make_session_id("discord", channel_id),
        user_id=user_id,
        text=text,
        message_id=message_id,
        correlation_id=correlation_id,
        reply_token=message_id,
        timestamp=time.time(),
    )
