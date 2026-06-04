"""Session finalization: when a conversation goes idle (its hot cache has
expired), fold it into durable memory so short/abandoned sessions still count.

- tier-2: fold the un-summarised tail into the channel summary (incremental via
  the summary's `covers_through_message_id` cursor — no double-folding).
- tier-3: force per-user fact extraction, bypassing the normal token threshold
  (a 10-min session rarely reaches it).

Driven by a periodic sweeper in the worker (see interfaces/worker.py). Postgres
stays authoritative; raw `messages` are never deleted.
"""

import logging
from datetime import datetime, timedelta, timezone

from core.persistence import repository as repo
from core.persistence.models import Session

log = logging.getLogger("finalizer")


async def finalize_session(deps, db, session: Session) -> None:
    """Fold one session's remaining content into tier-2 + tier-3, then mark it."""
    # --- tier-2: fold the tail not yet covered by the channel summary ---
    latest = await repo.get_latest_summary(db, session.id)
    covers = latest.covers_through_message_id if latest else None
    tail = await repo.load_session_messages_after(db, session.id, covers)
    if tail:
        summary_dict = (
            {
                "text": latest.summary_text,
                "turn_count": latest.turn_count,
                "covers_through_message_id": covers,
            }
            if latest
            else None
        )
        turns = [{"role": m.role, "content": m.content} for m in tail]
        new_summary = await deps.summarizer.fold_overflow(
            session.session_key, summary_dict, turns,
            covers_through_message_id=tail[-1].id,
        )
        if new_summary is not None:
            await repo.save_summary(
                db, session.id, new_summary["text"], new_summary["turn_count"],
                covers_through_message_id=tail[-1].id,
            )

    # --- tier-3: force fact extraction for each speaker (no token gate) ---
    for user_id in await repo.session_user_ids(db, session.id):
        user_key = f"{session.platform}:{user_id}"
        cursor = await deps.user_memory_store.get_cursor(db, user_key)
        pending = await repo.load_messages_after(db, user_id, cursor)
        if not pending:
            continue
        doc = await deps.user_memory_store.load(db, user_key)
        new_doc = await deps.fact_extractor.extract(user_key, doc, pending)
        await deps.user_memory_store.save(
            db, user_key, new_doc, last_extracted_message_id=pending[-1].id
        )

    session.finalized_at = datetime.now(timezone.utc)


async def sweep_idle_sessions(deps) -> int:
    """Finalise every session idle past the threshold and not yet finalised.
    Returns the number finalised. Per-session isolation: one failure doesn't
    block the rest."""
    settings = deps.settings
    cutoff = datetime.now(timezone.utc) - timedelta(
        seconds=settings.session_finalize_idle_seconds
    )
    finalised = 0
    async with deps.sessionmaker() as db:
        sessions = await repo.idle_unfinalized_sessions(
            db, cutoff, settings.session_sweep_batch
        )
        for session in sessions:
            try:
                await finalize_session(deps, db, session)
                await db.commit()
                finalised += 1
                log.info("finalised session %s", session.session_key)
            except Exception:  # noqa: BLE001 — keep sweeping other sessions
                log.exception("finalize failed for session %s", session.session_key)
                await db.rollback()
    return finalised
