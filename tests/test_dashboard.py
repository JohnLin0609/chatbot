"""DashboardStore aggregations over the eval tables."""

from core.eval.dashboard import DashboardStore
from core.persistence.models import (
    EvalChunkLabel,
    EvalGoldenRun,
    EvalJudgement,
    EvalRetrievedChunk,
    EvalTrace,
    LlmCall,
    MessageFeedback,
)
from tests.conftest import make_settings


async def _seed(sessionmaker):
    async with sessionmaker() as db:
        t = EvalTrace(query="q", reply_text="a")
        db.add(t)
        await db.flush()
        db.add_all([
            EvalJudgement(trace_id=t.id, metric="faithfulness", score=0.8, judge_run_id="r1"),
            EvalJudgement(trace_id=t.id, metric="answer_relevance", score=1.0, judge_run_id="r1"),
        ])
        c1 = EvalRetrievedChunk(trace_id=t.id, doc_id="d1", chunk_index=0, fused_rank=0, final_rank=0)
        c2 = EvalRetrievedChunk(trace_id=t.id, doc_id="d1", chunk_index=1, fused_rank=1, final_rank=1)
        db.add_all([c1, c2])
        await db.flush()
        db.add_all([
            EvalChunkLabel(trace_id=t.id, chunk_ref_id=c1.id, relevance=1.0, judge_run_id="r1"),
            EvalChunkLabel(trace_id=t.id, chunk_ref_id=c2.id, relevance=0.0, judge_run_id="r1"),
        ])
        db.add_all([
            LlmCall(call_type="main_reply", prompt_tokens=10, completion_tokens=5, latency_ms=100.0),
            LlmCall(call_type="judge", prompt_tokens=20, completion_tokens=8, latency_ms=200.0),
        ])
        db.add(EvalGoldenRun(num_queries=1, aggregate={"recall": {"1": 1.0}, "correctness": 0.9}))
        db.add(MessageFeedback(message_id=1, user_id="7", rating=1))
        await db.commit()


async def test_dashboard_summary(sessionmaker):
    await _seed(sessionmaker)
    store = DashboardStore(sessionmaker, make_settings(golden_eval_k_values=[1, 3]))
    data = await store.summary()

    ov = data["overview"]
    assert ov["traces"] == 1 and ov["judged_traces"] == 1
    assert ov["feedback_up"] == 1 and ov["llm_calls"] == 2

    gen = data["generation"]
    assert gen["current"]["faithfulness"] == 0.8
    assert len(gen["series"]) == 1 and gen["series"][0]["run"] == "r1"

    ret = data["retrieval"]["current"]
    assert ret["precision"]["1"] == 1.0 and ret["mrr"] == 1.0
    assert ret["hit_rate"]["1"] == 1.0

    cost = data["cost"]
    assert cost["totals"]["calls"] == 2 and cost["totals"]["tokens"] == 43
    types = {r["call_type"]: r for r in cost["by_call_type"]}
    assert types["judge"]["tokens"] == 28 and types["main_reply"]["tokens"] == 15

    golden = data["golden"]
    assert golden["series"][0]["aggregate"]["correctness"] == 0.9


async def test_dashboard_empty(sessionmaker):
    store = DashboardStore(sessionmaker, make_settings())
    data = await store.summary()
    assert data["overview"]["traces"] == 0
    assert data["generation"]["series"] == [] and data["retrieval"]["series"] == []
    assert data["cost"]["series"] == [] and data["golden"]["series"] == []
