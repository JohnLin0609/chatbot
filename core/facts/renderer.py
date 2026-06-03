"""Render per-user memory and channel summary into slimmed prompt text.

Facts are slimmed to `key: value` (metadata dropped) and ranked by
confidence × recency so the most relevant ones fit the token budget.
"""

import math
import re
from datetime import datetime, timezone

from core.config import Settings
from core.facts.schema import FactEntry, UserMemoryDocument
from core.tokens.counter import TokenCounter


def _render_value(entry: FactEntry) -> str:
    if isinstance(entry.value, list):
        return ", ".join(str(v) for v in entry.value)
    return str(entry.value)


def _recency_weight(entry: FactEntry, now: datetime, halflife_days: float) -> float:
    if halflife_days <= 0:
        return 1.0
    ref = entry.last_used_at or entry.updated_at
    age_days = max(0.0, (now - ref).total_seconds() / 86400.0)
    return math.exp(-age_days / halflife_days)


def _score(entry: FactEntry, settings: Settings, now: datetime) -> float:
    conf = max(entry.confidence, 1e-6) ** settings.fact_confidence_weight
    rec = _recency_weight(entry, now, settings.fact_recency_halflife_days)
    return conf * (rec ** settings.fact_recency_weight)


def render_personal_memory(
    doc: UserMemoryDocument,
    counter: TokenCounter,
    settings: Settings,
    now: datetime | None = None,
) -> tuple[str, list[str]]:
    """Return (rendered_text, fact_keys_used). Budget = personal_memory_token_cap."""
    now = now or datetime.now(timezone.utc)
    budget = settings.personal_memory_token_cap

    lines: list[str] = []
    used_keys: list[str] = []
    used_tokens = 0

    if doc.rolling_summary:
        lines.append(doc.rolling_summary)
        used_tokens += counter.count_text(doc.rolling_summary)

    ranked = sorted(
        doc.facts.items(),
        key=lambda kv: _score(kv[1], settings, now),
        reverse=True,
    )
    for key, entry in ranked:
        line = f"{key}: {_render_value(entry)}"
        cost = counter.count_text(line)
        if used_tokens + cost > budget:
            continue  # try smaller subsequent entries (whole-entry only)
        lines.append(line)
        used_keys.append(key)
        used_tokens += cost

    return "\n".join(lines), used_keys


def render_channel_summary(
    summary: dict | None, counter: TokenCounter, cap: int
) -> str:
    if not summary:
        return ""
    text = summary.get("text", "")
    if not text or counter.count_text(text) <= cap:
        return text
    # Truncate to whole sentences that fit under the cap.
    sentences = re.split(r"(?<=[.!?。！？\n])\s*", text)
    out, used = [], 0
    for sent in sentences:
        if not sent:
            continue
        cost = counter.count_text(sent)
        if out and used + cost > cap:
            break
        out.append(sent)
        used += cost
    return " ".join(out).strip()
