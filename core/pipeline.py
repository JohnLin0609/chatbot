"""Core message-handling pipeline: one inbound event -> one outbound event.

Platform-agnostic. Knows nothing about Line/Discord/HTTP — it consumes an
InboundEvent and produces an OutboundEvent, passing correlation/routing fields
through verbatim.
"""

import time
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import async_sessionmaker

from core.config import Settings
from core.llm.base import ChatService, ChatServiceError
from core.memory.context_builder import build_context
from core.memory.hot_store import HotStore
from core.persistence import repository as repo
from core.summary.summarizer import Summarizer
from shared.events import InboundEvent, OutboundEvent


@dataclass
class PipelineDeps:
    settings: Settings
    hot_store: HotStore
    sessionmaker: async_sessionmaker
    chat_service: ChatService
    summarizer: Summarizer


def _outbound(inbound: InboundEvent, *, text: str = "", status: str = "ok",
              error: str | None = None) -> OutboundEvent:
    return OutboundEvent(
        event_id=str(uuid.uuid4()),
        in_reply_to=inbound.event_id,
        platform=inbound.platform,
        channel_id=inbound.channel_id,
        session_id=inbound.session_id,
        correlation_id=inbound.correlation_id,
        reply_token=inbound.reply_token,
        text=text,
        status=status,
        error=error,
        timestamp=time.time(),
    )


async def handle_inbound(inbound: InboundEvent, deps: PipelineDeps) -> OutboundEvent:
    settings = deps.settings
    hot = deps.hot_store
    session_key = inbound.session_id

    async with deps.sessionmaker() as db:
        session_row = await repo.ensure_session(
            db, session_key, inbound.platform, inbound.channel_id
        )

        # Cold/expired hot store -> rebuild recent context from Postgres.
        if not await hot.exists(session_key):
            recent_rows = await repo.load_recent(
                db, session_row.id, limit=2 * settings.recent_turns
            )
            latest = await repo.get_latest_summary(db, session_row.id)
            backfill_turns = [
                {"role": m.role, "content": m.content} for m in recent_rows
            ]
            backfill_summary = (
                {"text": latest.summary_text, "turn_count": latest.turn_count,
                 "covers_through_message_id": latest.covers_through_message_id}
                if latest
                else None
            )
            await hot.backfill(session_key, backfill_summary, backfill_turns)

        summary, turns = await hot.load(session_key)
        messages = build_context(settings, summary, turns, inbound.text)

        try:
            reply = await deps.chat_service.generate_reply(session_key, messages)
        except ChatServiceError as exc:
            await db.rollback()
            return _outbound(inbound, status="error", error=str(exc))

        # Persist the turn (hot + durable) atomically on the DB side.
        await hot.append_turn(session_key, inbound.text, reply)
        await repo.append_message(
            db, session_row.id, "user", inbound.text,
            platform_message_id=inbound.message_id, user_id=inbound.user_id,
        )
        await repo.append_message(db, session_row.id, "assistant", reply)

        # Summarise if over threshold (updates hot store; persist returned summary).
        summary, turns = await hot.load(session_key)
        new_summary = await deps.summarizer.maybe_summarize(session_key, summary, turns)
        if new_summary is not None:
            await repo.save_summary(
                db, session_row.id, new_summary["text"], new_summary["turn_count"]
            )

        await db.commit()

    return _outbound(inbound, text=reply, status="ok")
