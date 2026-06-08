"""TraceStore: read-only access to individual eval traces for the admin
single-turn prompt-structure debug viewer. No writes, no migration.

The centerpiece is `_split_segments`: it decomposes the stored `messages` array
(assembled by `core.memory.context_builder.build_context`) back into its labelled
semantic layers — system prompt / channel summary / user memory / RAG knowledge /
tier-1 history / current query — each with an estimated token count + share, so the
frontend stays presentational.
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.persistence.models import (
    EvalChunkLabel,
    EvalJudgement,
    EvalRetrievedChunk,
    EvalTrace,
)
from core.tokens.counter import TokenCounter

# Leading system-block prefixes, in build_context order (context_builder.py). The
# persona (system_prompt) carries no prefix and is matched separately.
_SYSTEM_PREFIXES = (
    ("channel_summary", "Channel summary:\n", "Channel summary (tier-2)"),
    ("user_memory", "About the current speaker:\n", "User memory (tier-3)"),
    (
        "rag_knowledge",
        "Relevant knowledge (retrieved from the knowledge base; cite it if "
        "useful):\n",
        "RAG knowledge (tier-4)",
    ),
)


def _iso(dt):
    return dt.isoformat() if dt else None


def _f(v) -> float | None:
    return round(float(v), 4) if v is not None else None


class TraceStore:
    def __init__(self, sessionmaker: async_sessionmaker, settings) -> None:
        self._sm = sessionmaker
        self._settings = settings

    # ---------------------------------------------------------------- list
    async def list(
        self,
        *,
        tier: str | None = None,
        user_id: str | None = None,
        session_key: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict:
        limit = max(1, min(int(limit), 200))
        offset = max(0, int(offset))
        filters = []
        if tier:
            filters.append(EvalTrace.rag_tier == tier)
        if user_id:
            filters.append(EvalTrace.user_id == user_id)
        if session_key:
            filters.append(EvalTrace.session_key == session_key)

        async with self._sm() as db:
            total = (await db.execute(
                select(func.count()).select_from(EvalTrace).where(*filters)
            )).scalar_one()
            rows = (await db.execute(
                select(
                    EvalTrace.id, EvalTrace.created_at, EvalTrace.user_id,
                    EvalTrace.session_key, EvalTrace.rag_tier, EvalTrace.reranked,
                    EvalTrace.query, EvalTrace.prompt_tokens,
                    EvalTrace.completion_tokens, EvalTrace.total_latency_ms,
                    EvalTrace.model, EvalTrace.provider,
                )
                .where(*filters)
                .order_by(EvalTrace.created_at.desc(), EvalTrace.id.desc())
                .limit(limit).offset(offset)
            )).all()
        traces = [
            {
                "id": r.id, "created_at": _iso(r.created_at), "user_id": r.user_id,
                "session_key": r.session_key, "rag_tier": r.rag_tier,
                "reranked": r.reranked,
                "query_preview": (r.query or "")[:120],
                "prompt_tokens": r.prompt_tokens,
                "completion_tokens": r.completion_tokens,
                "total_latency_ms": _f(r.total_latency_ms),
                "model": r.model, "provider": r.provider,
            }
            for r in rows
        ]
        return {"traces": traces, "total": total, "limit": limit, "offset": offset}

    # -------------------------------------------------------------- detail
    async def detail(self, trace_id: int) -> dict | None:
        async with self._sm() as db:
            trace = await db.get(EvalTrace, trace_id)
            if trace is None:
                return None
            chunks = (await db.execute(
                select(EvalRetrievedChunk).where(
                    EvalRetrievedChunk.trace_id == trace_id
                )
            )).scalars().all()
            chunks = sorted(chunks, key=_chunk_order)
            judge = await self._latest_judge(db, trace_id, chunks)

        segments, bodies_logged = self._split_segments(trace)
        return {
            "trace": _trace_full(trace),
            "segments": segments,
            "messages": trace.messages,
            "bodies_logged": bodies_logged,
            "chunks": [_chunk_dict(c) for c in chunks],
            "judge": judge,
        }

    # -------------------------------------------------------- judge (latest)
    async def _latest_judge(self, db, trace_id: int, chunks) -> dict | None:
        latest = (await db.execute(
            select(EvalJudgement.judge_run_id, EvalJudgement.created_at)
            .where(EvalJudgement.trace_id == trace_id)
            .order_by(EvalJudgement.created_at.desc(), EvalJudgement.id.desc())
            .limit(1)
        )).first()
        if latest is None:
            return None
        run_id, at = latest
        jrows = (await db.execute(
            select(EvalJudgement).where(
                EvalJudgement.trace_id == trace_id,
                EvalJudgement.judge_run_id == run_id,
            )
        )).scalars().all()
        labels = (await db.execute(
            select(EvalChunkLabel).where(
                EvalChunkLabel.trace_id == trace_id,
                EvalChunkLabel.judge_run_id == run_id,
            )
        )).scalars().all()
        titles = {c.id: (c.title or c.doc_id) for c in chunks}
        first = jrows[0] if jrows else None
        return {
            "run_id": run_id,
            "at": _iso(at),
            "provider": first.judge_provider if first else None,
            "model": first.judge_model if first else None,
            "metrics": [
                {"metric": j.metric, "score": _f(j.score), "reasoning": j.reasoning}
                for j in jrows
            ],
            "chunk_labels": [
                {
                    "chunk_ref_id": label.chunk_ref_id,
                    "title": titles.get(label.chunk_ref_id),
                    "relevance": _f(label.relevance),
                    "reasoning": label.reasoning,
                }
                for label in labels
            ],
        }

    # ------------------------------------------------------ segment splitter
    def _split_segments(self, trace) -> tuple[list[dict], bool]:
        msgs = trace.messages
        if msgs is None:
            return [], False
        tc = TokenCounter(self._settings.tiktoken_encoding)
        msgs = list(msgs)

        # Peel the final user message first so history never swallows the query.
        current = None
        if msgs and msgs[-1].get("role") == "user":
            current = msgs.pop()

        segments: list[dict] = []
        history: list[dict] = []
        seen_system = False
        for m in msgs:
            role = m.get("role")
            content = m.get("content") or ""
            if role == "system":
                matched = next(
                    (
                        (kind, label, content[len(prefix):])
                        for kind, prefix, label in _SYSTEM_PREFIXES
                        if content.startswith(prefix)
                    ),
                    None,
                )
                if matched:
                    segments.append(_seg(tc, *matched))
                elif (trace.system_prompt is not None and content == trace.system_prompt) \
                        or not seen_system:
                    segments.append(_seg(tc, "system_prompt", "System prompt", content))
                else:
                    segments.append(_seg(tc, "system_other", "System (other)", content))
                seen_system = True
            else:
                history.append({"role": role, "content": content})

        if history:
            text = "\n".join(f"{t['role']}: {t['content']}" for t in history)
            seg = _seg(tc, "history", "Conversation history (tier-1)", text)
            seg["turns"] = history
            segments.append(seg)
        if current is not None:
            segments.append(
                _seg(tc, "current_query", "Current query", current.get("content") or "")
            )

        total = sum(s["tokens"] for s in segments) or 1
        for s in segments:
            s["pct"] = round(s["tokens"] / total, 4)
        return segments, True


def _seg(tc: TokenCounter, kind: str, label: str, content: str) -> dict:
    return {"kind": kind, "label": label, "content": content,
            "tokens": tc.count_text(content)}


def _chunk_order(c) -> tuple:
    rank = c.final_rank if c.final_rank is not None else (
        c.fused_rank if c.fused_rank is not None else 1_000_000
    )
    return (rank, c.id)


def _chunk_dict(c) -> dict:
    return {
        "id": c.id, "doc_id": c.doc_id, "chunk_index": c.chunk_index,
        "title": c.title, "chunk_text": c.chunk_text,
        "fused_score": _f(c.fused_score), "fused_rank": c.fused_rank,
        "rerank_score": _f(c.rerank_score), "final_rank": c.final_rank,
        "included": c.included, "content_type": c.content_type, "paired": c.paired,
    }


def _trace_full(t) -> dict:
    return {
        "id": t.id, "created_at": _iso(t.created_at), "user_id": t.user_id,
        "session_key": t.session_key, "conversation_id": t.conversation_id,
        "query": t.query, "rag_tier": t.rag_tier, "reranked": t.reranked,
        "reply_text": t.reply_text, "reply_message_id": t.reply_message_id,
        "system_prompt": t.system_prompt, "knowledge_text": t.knowledge_text,
        "prompt_tokens": t.prompt_tokens, "completion_tokens": t.completion_tokens,
        "model": t.model, "provider": t.provider,
        "tool_calls_count": t.tool_calls_count,
        "retrieval_latency_ms": _f(t.retrieval_latency_ms),
        "generation_latency_ms": _f(t.generation_latency_ms),
        "total_latency_ms": _f(t.total_latency_ms),
    }
