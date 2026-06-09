"""Core message-handling pipeline: one inbound event -> one outbound event.

Maintains three memory tiers:
  tier-1  token window of recent turns (per channel)
  tier-2  short running channel summary (folded from window overflow)
  tier-3  per-user durable facts + cross-session rolling summary

Platform-agnostic: passes correlation/routing fields through verbatim.
"""

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import async_sessionmaker

from core.config import Settings
from core.eval.logger import NullEvalLogger
from core.eval.schemas import CandidateRecord, RetrievalTrace
from core.facts.extractor import FactExtractor
from core.facts.renderer import render_channel_summary, render_personal_memory
from core.facts.store import UserMemoryStore
from core.llm.base import ChatService, ChatServiceError
from core.memory.context_builder import build_context
from core.memory.hot_store import HotStore
from core.memory.token_window import select_window
from core.persistence import repository as repo
from core.rag.classifier import COMPLEX, SIMPLE, QueryClassifier
from core.rag.embeddings import EmbeddingService
from core.rag.reranker import Reranker
from core.rag.retriever import RagRetriever
from core.rag.vector_store import QdrantVectorStore, chunk_point_id
from core.summary.summarizer import Summarizer
from core.tokens.counter import TokenCounter
from core.tools.loop import ToolRunner
from core.tools.schemas import ToolContext
from core.web.brave import BraveSearchService
from shared.events import InboundEvent, OutboundEvent
from shared.progress import ProgressEmitter

log = logging.getLogger("pipeline")


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
    tool_runner: ToolRunner
    embedding_service: EmbeddingService
    vector_store: QdrantVectorStore
    web_search_service: BraveSearchService | None = None
    progress_emitter: ProgressEmitter | None = None
    # Adaptive-RAG (optional; when absent the pipeline does no knowledge retrieval).
    classifier: QueryClassifier | None = None
    retriever: RagRetriever | None = None
    reranker: Reranker | None = None
    # Eval logging (defaults to a no-op so the pipeline is unconditional).
    eval_logger: "NullEvalLogger | object" = field(default_factory=NullEvalLogger)


def _outbound(inbound: InboundEvent, *, text: str = "", status: str = "ok",
              error: str | None = None, reply_message_id: int | None = None) -> OutboundEvent:
    return OutboundEvent(
        event_id=str(uuid.uuid4()),
        in_reply_to=inbound.event_id,
        platform=inbound.platform,
        channel_id=inbound.channel_id,
        session_id=inbound.session_id,
        correlation_id=inbound.correlation_id,
        reply_token=inbound.reply_token,
        text=text,
        reply_message_id=reply_message_id,
        status=status,
        error=error,
        timestamp=time.time(),
    )


def _source_label(hit) -> str:
    """A human-readable citation label: deck (from the doc title, extension
    stripped) plus the slide heading when available — e.g.
    `W14 例外處理 — 錯誤的種類`. Code chunks read `W05 conditionals — code:
    W05_條件判斷.py`. Falls back to the raw title / "untitled"."""
    p = hit.payload or {}
    if p.get("content_type") == "code":
        lec = p.get("lecture")
        wk = f"W{lec:02d}" if isinstance(lec, int) else ""
        fname = p.get("source_file") or hit.title or "code"
        head = " ".join(x for x in (wk, (p.get("topic") or "").strip()) if x)
        return f"{head} — code: {fname}".lstrip(" —") if head else f"code: {fname}"
    deck = hit.title or ""
    for ext in (".pptx", ".ppt"):
        if deck.lower().endswith(ext):
            deck = deck[: -len(ext)]
            break
    deck = deck.replace("_", " ").strip()
    slide = (p.get("metadata") or {}).get("title")
    parts = [s for s in (deck, (slide or "").strip()) if s]
    return " — ".join(parts) or "untitled"


def _format_knowledge(hits) -> str:
    lines = []
    for i, hit in enumerate(hits, start=1):
        lines.append(f"[{i}] ({_source_label(hit)}) {hit.text}")
    return "\n".join(lines)


def _candidate(hit, fused_rank: int) -> "CandidateRecord":
    p = hit.payload or {}
    doc_id = p.get("doc_id")
    chunk_index = p.get("chunk_index")
    return CandidateRecord(
        doc_id=doc_id,
        chunk_index=chunk_index,
        point_id=chunk_point_id(doc_id, chunk_index) if doc_id is not None else None,
        title=hit.title,
        chunk_text=hit.text,
        fused_score=hit.score,
        fused_rank=fused_rank,
        rerank_score=getattr(hit, "rerank_score", None),
        content_type=p.get("content_type"),
    )


async def _pair_code(settings, vector_store, final: list, candidates: list) -> list:
    """For each retrieved *slide* hit, fetch its paired example *code* (same
    lecture) so explanation + runnable example arrive together. Additive (beyond
    top_k), deduped by lecture and against already-retrieved chunks, capped.
    Reused by the golden runner so its generation matches the live chat path."""
    if not getattr(settings, "rag_pair_code_enabled", False):
        return []
    store = vector_store
    if store is None:
        return []
    cap = settings.rag_pair_code_max
    present = {((h.payload or {}).get("doc_id"), (h.payload or {}).get("chunk_index"))
               for h in candidates}
    seen_lectures: set = set()
    paired: list = []
    for h in final:
        p = h.payload or {}
        if p.get("content_type") != "slide":
            continue
        lec = p.get("lecture")
        if lec is None or lec in seen_lectures:
            continue
        seen_lectures.add(lec)
        for code_hit in await store.fetch_paired("code", lec, limit=cap):
            cp = code_hit.payload or {}
            key = (cp.get("doc_id"), cp.get("chunk_index"))
            if key in present:
                continue
            present.add(key)
            paired.append(code_hit)
            if len(paired) >= cap:
                return paired
    return paired


async def _retrieve_knowledge(
    deps: "PipelineDeps", query: str
) -> tuple[str, "RetrievalTrace | None"]:
    """Adaptive-RAG: classify the query, then retrieve (and optionally rerank)
    curated knowledge. Returns (formatted block to inject, RetrievalTrace). The
    block is "" for simple queries / when retrieval is not wired; the trace
    captures every candidate + scores/ranks + final disposition for eval logging.
    Best-effort — never raises."""
    if not (deps.classifier and deps.retriever):
        return "", None
    settings = deps.settings
    try:
        tier = await deps.classifier.classify(query)
        if tier == SIMPLE:
            return "", RetrievalTrace(tier=SIMPLE, reranked=False, candidates=[])

        if tier == COMPLEX:
            candidates = await deps.retriever.retrieve(
                query, top_k=settings.rag_complex_candidates
            )
            reranked = deps.reranker is not None
            if reranked:
                final = await deps.reranker.rerank(
                    query, list(candidates), settings.rag_complex_top_k
                )
            else:
                final = candidates[: settings.rag_complex_top_k]
        else:  # medium
            candidates = await deps.retriever.retrieve(
                query, top_k=settings.rag_medium_top_k
            )
            reranked = False
            final = candidates

        # Build the trace: every candidate (fused rank by retrieval order), with
        # included/final_rank set for those that entered the injected top-k.
        recs = [_candidate(h, i) for i, h in enumerate(candidates)]
        final_ids = {id(h): r for r, h in enumerate(final)}
        for rec, h in zip(recs, candidates):
            if id(h) in final_ids:
                rec.included = True
                rec.final_rank = final_ids[id(h)]
                rec.rerank_score = getattr(h, "rerank_score", None)

        # Slide → code binding: pull each retrieved slide's paired example code
        # and inject it alongside (additive). Recorded in the trace as paired.
        paired = await _pair_code(deps.settings, deps.vector_store, final, candidates)
        for code_hit in paired:
            rec = _candidate(code_hit, None)
            rec.included = True
            rec.paired = True
            recs.append(rec)

        trace = RetrievalTrace(tier=tier, reranked=reranked, candidates=recs)
        return _format_knowledge(list(final) + paired), trace
    except Exception:  # noqa: BLE001 — retrieval must never break the reply
        log.warning("knowledge retrieval failed", exc_info=True)
        return "", None


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
        # tier-4: Adaptive-RAG — classify, retrieve (+rerank), inject knowledge.
        _t_retr = time.perf_counter()
        knowledge_text, retrieval_trace = await _retrieve_knowledge(deps, inbound.text)
        retrieval_ms = (time.perf_counter() - _t_retr) * 1000
        # admin-set global persona override (None/empty -> settings default).
        system_prompt = await repo.get_app_setting(db, "system_prompt")
        messages = build_context(
            settings,
            channel_summary_text=channel_text,
            personal_memory_text=personal_text,
            window_turns=window_turns,
            user_text=inbound.text,
            knowledge_text=knowledge_text,
            system_prompt=system_prompt,
        )

        # Main reply runs through the tool-calling loop (the model may call
        # search_knowledge). tier-1/2/3 injection above is unchanged; RAG only
        # enters via tools. Degrades to a single completion when tools are off.
        tool_ctx = ToolContext(
            settings=settings,
            embedding_service=deps.embedding_service,
            vector_store=deps.vector_store,
            session_id=session_key,
            user_key=user_key,
            channel_id=inbound.channel_id,
            web_search_service=deps.web_search_service,
            correlation_id=inbound.correlation_id,
            progress=deps.progress_emitter,
        )
        _t_gen = time.perf_counter()
        try:
            reply = await deps.tool_runner.run(session_key, messages, tool_ctx)
        except ChatServiceError as exc:
            await db.rollback()
            return _outbound(inbound, status="error", error=str(exc))
        generation_ms = (time.perf_counter() - _t_gen) * 1000

        # --- persist the turn (hot + durable) ---
        await hot.append_turn(session_key, inbound.text, reply, user_id=inbound.user_id)
        await repo.append_message(
            db, session_row.id, "user", inbound.text,
            platform_message_id=inbound.message_id, user_id=inbound.user_id,
        )
        assistant_msg = await repo.append_message(
            db, session_row.id, "assistant", reply
        )
        # Capture ids now; reading them after db.commit() would trigger expiry IO.
        reply_message_id = assistant_msg.id
        session_db_id = session_row.id

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

    # --- eval logging (best-effort, fire-and-forget) ---
    asyncio.create_task(deps.eval_logger.log_trace(
        event_id=inbound.event_id,
        correlation_id=inbound.correlation_id,
        session_db_id=session_db_id,
        session_key=session_key,
        user_id=inbound.user_id,
        conversation_id=inbound.channel_id,
        query=inbound.text,
        retrieval=retrieval_trace,
        system_prompt=system_prompt,
        knowledge_text=knowledge_text,
        messages=messages,
        reply_text=reply,
        reply_message_id=reply_message_id,
        retrieval_latency_ms=retrieval_ms,
        generation_latency_ms=generation_ms,
    ))

    return _outbound(inbound, text=reply, status="ok", reply_message_id=reply_message_id)


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
