"""Real TraceStore over the in-memory DB: segment splitting, chunk ordering,
latest-judge selection, and the bodies-not-logged degradation path."""

from datetime import datetime, timezone

import pytest_asyncio

from core.eval.trace_store import TraceStore
from core.memory.context_builder import build_context
from core.persistence.models import (
    EvalChunkLabel,
    EvalJudgement,
    EvalRetrievedChunk,
    EvalTrace,
)
from core.tokens.counter import TokenCounter
from tests.conftest import make_settings

S = make_settings(system_prompt="You are helpful.")
KNOWLEDGE = "[1] (Refund Policy) refunds within 14 days"
QUERY = "How long for a refund?"


def _messages():
    return build_context(
        S,
        channel_summary_text="Prior chat about refunds.",
        personal_memory_text="The speaker is John.",
        window_turns=[
            {"role": "user", "content": "earlier question"},
            {"role": "assistant", "content": "earlier answer"},
        ],
        user_text=QUERY,
        knowledge_text=KNOWLEDGE,
        system_prompt="You are helpful.",
    )


@pytest_asyncio.fixture
async def seeded(sessionmaker):
    """One complex trace with mixed chunks + two judge runs (old, new)."""
    async with sessionmaker() as db:
        trace = EvalTrace(
            session_key="web:7:c1", user_id="7", conversation_id="7:c1",
            query=QUERY, rag_tier="complex", reranked=True,
            system_prompt="You are helpful.", knowledge_text=KNOWLEDGE,
            messages=_messages(), reply_text="Within 14 days.",
            prompt_tokens=123, completion_tokens=7, model="gpt-x", provider="openai",
            retrieval_latency_ms=12.0, generation_latency_ms=80.0, total_latency_ms=92.0,
        )
        db.add(trace)
        await db.flush()
        included = EvalRetrievedChunk(
            trace_id=trace.id, doc_id="d1", chunk_index=0, title="Refund Policy",
            chunk_text="refunds within 14 days", fused_score=0.9, fused_rank=1,
            rerank_score=0.95, final_rank=0, included=True,
        )
        dropped = EvalRetrievedChunk(
            trace_id=trace.id, doc_id="d2", chunk_index=3, title="Shipping",
            chunk_text="ships in 3 days", fused_score=0.4, fused_rank=5,
            rerank_score=0.1, final_rank=None, included=False,
        )
        db.add_all([included, dropped])
        await db.flush()
        # two judge runs; the store must pick the newer by created_at
        db.add(EvalJudgement(
            trace_id=trace.id, metric="faithfulness", score=0.5, reasoning="old",
            judge_run_id="r_old", judge_model="j",
            created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        ))
        db.add(EvalJudgement(
            trace_id=trace.id, metric="faithfulness", score=0.9, reasoning="new",
            judge_run_id="r_new", judge_model="j",
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        ))
        db.add(EvalChunkLabel(
            trace_id=trace.id, chunk_ref_id=included.id, relevance=1.0,
            reasoning="on-topic", judge_run_id="r_new",
            created_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        ))
        await db.commit()
        return trace.id


async def test_segments_decompose_in_order(sessionmaker, seeded):
    detail = await TraceStore(sessionmaker, S).detail(seeded)
    assert detail["bodies_logged"] is True
    kinds = [s["kind"] for s in detail["segments"]]
    assert kinds == [
        "system_prompt", "channel_summary", "user_memory", "rag_knowledge",
        "history", "current_query",
    ]
    by_kind = {s["kind"]: s for s in detail["segments"]}
    # the RAG block content is the bare knowledge_text (prefix stripped) and its
    # token count matches a direct TokenCounter estimate (encoding-independent).
    assert by_kind["rag_knowledge"]["content"] == KNOWLEDGE
    assert by_kind["rag_knowledge"]["tokens"] == \
        TokenCounter(S.tiktoken_encoding).count_text(KNOWLEDGE)
    # the final user message is the current query, not swallowed into history.
    assert by_kind["current_query"]["content"] == QUERY
    assert "earlier question" not in by_kind["current_query"]["content"]
    assert by_kind["history"]["turns"][0]["content"] == "earlier question"
    # pct shares sum to ~1.
    assert abs(sum(s["pct"] for s in detail["segments"]) - 1.0) < 0.05


async def test_chunks_ordered_and_judge_latest(sessionmaker, seeded):
    detail = await TraceStore(sessionmaker, S).detail(seeded)
    # included (final_rank 0) sorts before the dropped candidate (no final rank).
    assert [c["doc_id"] for c in detail["chunks"]] == ["d1", "d2"]
    assert detail["chunks"][0]["included"] is True
    assert detail["chunks"][1]["included"] is False
    # latest judge run wins.
    assert detail["judge"]["run_id"] == "r_new"
    assert detail["judge"]["metrics"][0]["score"] == 0.9
    assert detail["judge"]["chunk_labels"][0]["title"] == "Refund Policy"


async def test_list_filters_and_preview(sessionmaker, seeded):
    store = TraceStore(sessionmaker, S)
    res = await store.list(tier="complex")
    assert res["total"] == 1 and res["traces"][0]["query_preview"] == QUERY
    # a non-matching filter yields nothing.
    assert (await store.list(tier="simple"))["total"] == 0
    assert (await store.list(user_id="999"))["total"] == 0


async def test_bodies_not_logged_degrades(sessionmaker):
    async with sessionmaker() as db:
        t = EvalTrace(session_key="web:7:c2", user_id="7", rag_tier="simple",
                      query=None, messages=None, prompt_tokens=10)
        db.add(t)
        await db.commit()
        tid = t.id
    detail = await TraceStore(sessionmaker, S).detail(tid)
    assert detail["bodies_logged"] is False
    assert detail["segments"] == []
    assert detail["messages"] is None


async def test_detail_missing_returns_none(sessionmaker):
    assert await TraceStore(sessionmaker, S).detail(123456) is None
