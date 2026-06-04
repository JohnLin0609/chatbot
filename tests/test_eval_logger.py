"""EvalLogger writes parent+child trace rows and lightweight llm_call rows."""

from sqlalchemy import select

from core.eval.logger import EvalLogger
from core.eval.schemas import CandidateRecord, RetrievalTrace
from core.persistence.models import EvalRetrievedChunk, EvalTrace, LlmCall
from core.tokens.counter import TokenCounter
from tests.conftest import make_settings


def _logger(sessionmaker, **over):
    s = make_settings(**over)
    return EvalLogger(sessionmaker, TokenCounter(s.tiktoken_encoding), s)


def _trace(tier="complex", reranked=True):
    return RetrievalTrace(
        tier=tier, reranked=reranked,
        candidates=[
            CandidateRecord(doc_id="d1", chunk_index=0, point_id="p0", title="T",
                            chunk_text="alpha", fused_score=0.9, fused_rank=0,
                            rerank_score=0.8, final_rank=0, included=True),
            CandidateRecord(doc_id="d1", chunk_index=1, point_id="p1", title="T",
                            chunk_text="beta", fused_score=0.5, fused_rank=1,
                            rerank_score=0.2, final_rank=None, included=False),
        ],
    )


async def test_log_trace_writes_parent_and_children(sessionmaker):
    await _logger(sessionmaker).log_trace(
        event_id="e1", correlation_id="c1", session_db_id=None,
        session_key="web:7:c1", user_id="7", conversation_id="7:c1",
        query="how do refunds work?", retrieval=_trace(),
        system_prompt="be helpful", knowledge_text="[1] ...",
        messages=[{"role": "user", "content": "how do refunds work?"}],
        reply_text="14 days", reply_message_id=None,
        retrieval_latency_ms=12.0, generation_latency_ms=88.0,
    )
    async with sessionmaker() as db:
        trace = (await db.execute(select(EvalTrace))).scalar_one()
        chunks = (await db.execute(
            select(EvalRetrievedChunk).order_by(EvalRetrievedChunk.fused_rank)
        )).scalars().all()

    assert trace.rag_tier == "complex" and trace.reranked is True
    assert trace.query == "how do refunds work?" and trace.reply_text == "14 days"
    assert trace.prompt_tokens and trace.completion_tokens  # tiktoken estimates
    assert trace.total_latency_ms == 100.0
    assert len(chunks) == 2
    assert chunks[0].included is True and chunks[0].final_rank == 0
    assert chunks[0].rerank_score == 0.8
    assert chunks[1].included is False and chunks[1].final_rank is None


async def test_log_trace_nulls_bodies_when_disabled(sessionmaker):
    await _logger(sessionmaker, eval_log_message_bodies=False).log_trace(
        event_id="e1", correlation_id="c1", session_db_id=None,
        session_key="web:7:c1", user_id="7", conversation_id="7:c1",
        query="secret question", retrieval=_trace(),
        system_prompt="sys", knowledge_text="k",
        messages=[{"role": "user", "content": "secret question"}],
        reply_text="secret answer", reply_message_id=None,
    )
    async with sessionmaker() as db:
        trace = (await db.execute(select(EvalTrace))).scalar_one()
        chunk = (await db.execute(select(EvalRetrievedChunk).limit(1))).scalar_one()
    # bodies nulled, but token counts + scores/metadata retained
    assert trace.query is None and trace.reply_text is None and trace.messages is None
    assert trace.prompt_tokens and trace.completion_tokens
    assert chunk.chunk_text is None and chunk.fused_score == 0.9


async def test_log_call_writes_row(sessionmaker):
    await _logger(sessionmaker).log_call(
        "classifier", messages=[{"role": "user", "content": "hi there"}],
        output_text="medium", latency_ms=5.0, session_key="classify",
    )
    async with sessionmaker() as db:
        row = (await db.execute(select(LlmCall))).scalar_one()
    assert row.call_type == "classifier" and row.ok is True
    assert row.prompt_tokens and row.completion_tokens and row.latency_ms == 5.0


async def test_log_trace_never_raises(sessionmaker):
    # A broken sessionmaker must not propagate out of the logger.
    def boom():
        raise RuntimeError("db down")

    logger = EvalLogger(boom, TokenCounter("o200k_base"), make_settings())
    # should swallow the error
    await logger.log_trace(
        event_id=None, correlation_id=None, session_db_id=None, session_key=None,
        user_id=None, conversation_id=None, query="q", retrieval=None,
        system_prompt=None, knowledge_text=None, messages=[], reply_text="x",
        reply_message_id=None,
    )
    await logger.log_call("main_reply", messages=[], output_text="x")
