"""JudgeRunner: judges only un-judged traces, writes rows, idempotent, resilient."""

from sqlalchemy import func, select

from core.eval.judge import ChunkLabel, JudgementResult, MetricScore
from core.eval.runner import JudgeRunner
from core.persistence.models import (
    EvalChunkLabel,
    EvalJudgement,
    EvalRetrievedChunk,
    EvalTrace,
)
from tests.conftest import make_settings


class FakeJudge:
    def __init__(self, fail_ids=()):
        self.fail_ids = set(fail_ids)
        self.seen = []

    async def judge_trace(self, trace, chunks):
        self.seen.append(trace.id)
        if trace.id in self.fail_ids:
            raise RuntimeError("boom")
        labels = [ChunkLabel(chunk_ref_id=c.id, relevance=1.0, reasoning="r")
                  for c in chunks]
        return JudgementResult(
            metrics=[MetricScore("answer_relevance", 0.9, "good")],
            chunk_labels=labels,
        )


async def _seed_trace(sm, *, query="q", reply="a", chunks=0):
    async with sm() as db:
        t = EvalTrace(query=query, reply_text=reply, rag_tier="medium")
        db.add(t)
        await db.flush()
        for i in range(chunks):
            db.add(EvalRetrievedChunk(trace_id=t.id, doc_id="d1", chunk_index=i,
                                      fused_rank=i, chunk_text=f"c{i}", included=True))
        await db.commit()
        return t.id


async def test_run_batch_judges_unjudged_and_is_idempotent(sessionmaker):
    tid = await _seed_trace(sessionmaker, chunks=2)
    judge = FakeJudge()
    runner = JudgeRunner(sessionmaker, judge, make_settings())

    res = await runner.run_batch()
    assert res["judged"] == 1 and res["remaining"] == 0

    async with sessionmaker() as db:
        judgements = (await db.execute(select(EvalJudgement))).scalars().all()
        labels = (await db.execute(select(EvalChunkLabel))).scalars().all()
    assert [j.metric for j in judgements] == ["answer_relevance"]
    assert judgements[0].trace_id == tid and judgements[0].judge_run_id
    assert len(labels) == 2 and all(l.relevance == 1.0 for l in labels)

    # second run: nothing left to judge
    res2 = await runner.run_batch()
    assert res2["judged"] == 0


async def test_run_batch_skips_bodyless_traces(sessionmaker):
    await _seed_trace(sessionmaker, query=None, reply=None)  # bodies nulled
    runner = JudgeRunner(sessionmaker, FakeJudge(), make_settings())
    res = await runner.run_batch()
    assert res["judged"] == 0 and res["skipped"] == 1


async def test_run_batch_survives_a_failing_trace(sessionmaker):
    good = await _seed_trace(sessionmaker)
    bad = await _seed_trace(sessionmaker)
    runner = JudgeRunner(sessionmaker, FakeJudge(fail_ids={bad}), make_settings())
    res = await runner.run_batch()
    # the good one is judged; the failing one is left un-judged
    assert res["judged"] == 1 and res["remaining"] == 1
    async with sessionmaker() as db:
        judged_ids = (await db.execute(
            select(EvalJudgement.trace_id).distinct())).scalars().all()
    assert judged_ids == [good]


async def test_status_aggregates(sessionmaker):
    await _seed_trace(sessionmaker)
    runner = JudgeRunner(sessionmaker, FakeJudge(), make_settings())
    await runner.run_batch()
    st = await runner.status()
    assert st["total_traces"] == 1 and st["judged"] == 1 and st["unjudged"] == 0
    assert st["avg_scores"]["answer_relevance"] == 0.9
