"""FactExtractor: decide when to extract, call the LLM, merge the delta.

DB-agnostic about transactions — operates on a passed AsyncSession via the repo.
The LLM returns a delta JSON; this module applies cardinality / supersede rules
to produce the new UserMemoryDocument.
"""

import json
from datetime import datetime, timezone

from core.config import Settings
from core.facts.schema import FactEntry, SupersededEntry, UserMemoryDocument
from core.llm.base import ChatService
from core.persistence import repository as repo
from core.tokens.counter import TokenCounter


def _extract_json(raw: str) -> dict:
    """Tolerant JSON parse: take the first balanced {...} object."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    start = raw.find("{")
    if start == -1:
        return {}
    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


def _render_doc_for_prompt(doc: UserMemoryDocument) -> str:
    lines = [f"rolling_summary: {doc.rolling_summary or '(none)'}", "facts:"]
    for key, entry in doc.facts.items():
        val = entry.value if not isinstance(entry.value, list) else ", ".join(entry.value)
        lines.append(f"  {key} [{entry.cardinality}] = {val} (conf {entry.confidence})")
    return "\n".join(lines)


def _format_messages(messages) -> str:
    return "\n".join(f"{m.role}: {m.content}" for m in messages)


def _apply_delta(
    doc: UserMemoryDocument, delta: dict, source: str | None, now: datetime
) -> UserMemoryDocument:
    # rolling_summary
    new_summary = delta.get("rolling_summary")
    if isinstance(new_summary, str) and new_summary.strip():
        doc.rolling_summary = new_summary.strip()
        doc.summary_updated_at = now

    for item in delta.get("facts", []) or []:
        key = item.get("key")
        if not key or "value" not in item:
            continue
        value = item["value"]
        cardinality = item.get("cardinality", "single")
        confidence = float(item.get("confidence", 0.5))
        existing = doc.facts.get(key)

        if cardinality == "multi":
            current = list(existing.value) if existing and isinstance(existing.value, list) else []
            incoming = value if isinstance(value, list) else [value]
            merged = current + [v for v in incoming if v not in current]
            doc.facts[key] = FactEntry(
                cardinality="multi", value=merged,
                confidence=max(confidence, existing.confidence) if existing else confidence,
                source=source,
                created_at=existing.created_at if existing else now,
                updated_at=now,
                last_used_at=existing.last_used_at if existing else None,
            )
        else:  # single
            if existing and existing.value != value:
                doc.superseded.append(
                    SupersededEntry(key=key, value=existing.value, retired_at=now,
                                    reason="updated")
                )
            doc.facts[key] = FactEntry(
                cardinality="single", value=value, confidence=confidence, source=source,
                created_at=existing.created_at if existing else now,
                updated_at=now,
                last_used_at=existing.last_used_at if existing else None,
            )

    # Guard against a self-contradictory delta: if the LLM both sets a new value
    # for a key (in facts) and retires it, the new value wins — ignore the
    # retire. A value that merely changed is a replace, not a retirement.
    fact_keys = {item.get("key") for item in delta.get("facts", []) or []}
    for item in delta.get("retire", []) or []:
        key = item.get("key")
        if not key or key in fact_keys:
            continue
        entry = doc.facts.pop(key, None)
        if entry is not None:
            doc.superseded.append(
                SupersededEntry(key=key, value=entry.value, retired_at=now,
                                reason=item.get("reason"))
            )
    return doc


class FactExtractor:
    def __init__(self, settings: Settings, chat_service: ChatService,
                 counter: TokenCounter) -> None:
        self._settings = settings
        self._chat = chat_service
        self._counter = counter

    async def should_extract(self, db, user_id: str, cursor: int | None):
        """Return (should, pending_messages). pending = user's msgs after cursor."""
        pending = await repo.load_messages_after(db, user_id, cursor)
        turns = [{"role": m.role, "content": m.content} for m in pending]
        enough = self._counter.count_turns(turns) >= self._settings.fact_extraction_tokens
        return enough, pending

    async def extract(self, user_key: str, doc: UserMemoryDocument,
                      pending_messages) -> UserMemoryDocument:
        source = f"conv_{pending_messages[-1].id}" if pending_messages else None
        prompt = (
            f"Current memory:\n{_render_doc_for_prompt(doc)}\n\n"
            f"Recent messages:\n{_format_messages(pending_messages)}\n\n"
            "Return the JSON delta."
        )
        messages = [
            {"role": "system", "content": self._settings.fact_system_prompt},
            {"role": "user", "content": prompt},
        ]
        raw = await self._chat.generate_reply(user_key, messages)
        delta = _extract_json(raw)
        now = datetime.now(timezone.utc)
        return _apply_delta(doc, delta, source, now)
