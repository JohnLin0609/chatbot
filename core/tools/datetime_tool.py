"""The current_datetime tool: the current date + time, default Asia/Taipei.

Always available (no external dependency / API key) so the model can ground
time-relative questions ("today", "this week", "what day is it") instead of
guessing from its training cutoff.
"""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from core.tools.registry import tool
from core.tools.schemas import ToolContext

_DEFAULT_TZ = "Asia/Taipei"

_SCHEMA = {
    "type": "object",
    "properties": {
        "timezone": {
            "type": "string",
            "description": (
                "IANA timezone name (e.g. 'Asia/Taipei', 'UTC', "
                "'America/New_York'). Defaults to Asia/Taipei."
            ),
        },
    },
}


def _resolve_tz(name: str):
    """ZoneInfo for `name`, falling back to Asia/Taipei, then a fixed +08:00 — so
    the tool never errors even if the tz database is unavailable."""
    try:
        return ZoneInfo(name), name
    except Exception:  # noqa: BLE001 — unknown name / missing tzdata
        pass
    try:
        return ZoneInfo(_DEFAULT_TZ), _DEFAULT_TZ
    except Exception:  # noqa: BLE001 — no tzdata at all
        return timezone(timedelta(hours=8)), f"{_DEFAULT_TZ} (UTC+8)"


@tool(
    name="current_datetime",
    description=(
        "Get the current date and time. Use this for any time-relative question "
        "— today's date, the current time, the day of the week, or how recent "
        "something is — instead of guessing. Defaults to the Asia/Taipei timezone."
    ),
    parameters=_SCHEMA,
)
async def current_datetime(args: dict, ctx: ToolContext) -> str:
    name = (args.get("timezone") or _DEFAULT_TZ).strip() or _DEFAULT_TZ
    tz, resolved = _resolve_tz(name)
    now = datetime.now(tz)
    return f"{now.strftime('%Y-%m-%d %A %H:%M:%S %Z%z')} ({resolved})"
