"""Core message-handling pipeline: one inbound event -> one outbound event.

Maintains three memory tiers:
  tier-1  token window of recent turns (per channel)
  tier-2  short running channel summary (folded from window overflow)
  tier-3  per-user durable facts + cross-session rolling summary

Platform-agnostic: passes correlation/routing fields through verbatim.
"""

import asyncio
import time
import uuid
from dataclasses import dataclass

from sqlalchemy.ext.asyncio import async_sessionmaker

from core.config import Settings
from core.facts.extractor import FactExtractor
from core.facts.renderer import render_channel_summary, render_personal_memory
from core.facts.store import UserMemoryStore
from core.llm.base import ChatService, ChatServiceError
from core.memory.context_builder import build_context
from core.memory.hot_store import HotStore
from core.memory.token_window import select_window
from core.persistence import repository as repo
from core.summary.summarizer import Summarizer
from core.tokens.counter import TokenCounter
from shared.events import InboundEvent, OutboundEvent


@dataclass
class PipelineDeps:
    settings: Settings
    hot_store: HotStore
    sessionmaker: async_sessionmaker
    chat_service: ChatService
    summarizer: Summarizer
    token_counter: TokenCounter
    user_memory_store: UserMemoryStore
    fact_extractor: FactExtractor


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
    counter = deps.token_counter
    session_key = inbound.session_id
    user_key = f"{inbound.platform}:{inbound.user_id}"

    async with deps.sessionmaker() as db:
        session_row = await repo.ensure_session(
            db, session_key, inbound.platform, inbound.channel_id
        )

        # --- cold/expired hot store -> rebuild recent context from Postgres ---
        if not await hot.exists(session_key):
            recent_rows = await repo.load_recent(db, session_row.id, limit=200)
            latest = await repo.get_latest_summary(db, session_row.id)
            backfill_turns = [
                {"role": m.role, "content": m.content, "ts": 0, "user_id": m.user_id}
                for m in recent_rows
            ]
            backfill_summary = (
                {"text": latest.summary_text, "turn_count": latest.turn_count,
                 "covers_through_message_id": latest.covers_through_message_id}
                if latest else None
            )
            await hot.backfill(session_key, backfill_summary, backfill_turns)

        summary, turns = await hot.load(session_key)
        user_doc = await deps.user_memory_store.load(db, user_key)

        # --- assemble context (tier-1 window + tier-2 channel + tier-3 personal) ---
        window_turns, _ = select_window(counter, turns, settings.context_window_tokens)
        channel_text = render_channel_summary(
            summary, counter, settings.channel_summary_token_cap
        )
        personal_text, used_keys = render_personal_memory(user_doc, counter, settings)
        messages = build_context(
            settings,
            channel_summary_text=channel_text,
            personal_memory_text=personal_text,
            window_turns=window_turns,
            user_text=inbound.text,
        )

        try:
            reply = await deps.chat_service.generate_reply(session_key, messages)
        except ChatServiceError as exc:
            await db.rollback()
            return _outbound(inbound, status="error", error=str(exc))

        # --- persist the turn (hot + durable) ---
        await hot.append_turn(session_key, inbound.text, reply, user_id=inbound.user_id)
        await repo.append_message(
            db, session_row.id, "user", inbound.text,
            platform_message_id=inbound.message_id, user_id=inbound.user_id,
        )
        await repo.append_message(db, session_row.id, "assistant", reply)

        # --- tier-2: fold any window overflow into the channel summary ---
        summary, turns = await hot.load(session_key)
        window_turns, overflow = select_window(
            counter, turns, settings.context_window_tokens
        )
        if overflow:
            new_summary = await deps.summarizer.fold_overflow(
                session_key, summary, overflow
            )
            if new_summary is not None:
                await hot.set_summary(session_key, new_summary)
                await hot.replace_turns(session_key, window_turns)
                await repo.save_summary(
                    db, session_row.id, new_summary["text"], new_summary["turn_count"]
                )

        # --- tier-3: per-user fact extraction at the higher water-level ---
        if settings.fact_extraction_async:
            asyncio.create_task(
                _extract_facts_async(deps, user_key, inbound.user_id)
            )
        else:
            await _maybe_extract_facts(deps, db, user_key, inbound.user_id)

        # --- mark which facts were used in this prompt ---
        if used_keys:
            await deps.user_memory_store.bump_last_used(db, user_key, used_keys)

        await db.commit()

    return _outbound(inbound, text=reply, status="ok")


async def _maybe_extract_facts(deps, db, user_key: str, user_id: str) -> None:
    cursor = await deps.user_memory_store.get_cursor(db, user_key)
    should, pending = await deps.fact_extractor.should_extract(db, user_id, cursor)
    if not should or not pending:
        return
    doc = await deps.user_memory_store.load(db, user_key)
    new_doc = await deps.fact_extractor.extract(user_key, doc, pending)
    # cursor advances ONLY here, after a successful extraction. The mid-band
    # (evicted from window, folded into summary, not yet extracted) stays in
    # Postgres messages until this point — it is never lost.
    await deps.user_memory_store.save(
        db, user_key, new_doc, last_extracted_message_id=pending[-1].id
    )


async def _extract_facts_async(deps, user_key: str, user_id: str) -> None:
    """Background extraction in its own DB session/transaction."""
    async with deps.sessionmaker() as db:
        await _maybe_extract_facts(deps, db, user_key, user_id)
        await db.commit()
