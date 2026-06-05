"""JudgeRunner: batch-score un-judged eval_traces with the LLM-as-judge.

Picks traces that have no eval_judgements yet, scores each, and writes the
judgement + chunk-label rows. Commits per trace so one failure never aborts the
batch. Used by the CLI (`interfaces/judge.py`) and the admin endpoint.
"""

import logging
import uuid

from sqlalchemy import func, select

from core.eval.judge import Judge
from core.persistence.models import (
    EvalChunkLabel,
    EvalJudgement,
    EvalRetrievedChunk,
    EvalTrace,
)

log = logging.getLogger("eval.runner")


class JudgeRunner:
    def __init__(self, sessionmaker, judge: Judge, settings) -> None:
        self._sm = sessionmaker
        self._judge = judge
        self._settings = settings

    @property
    def _provider(self) -> str:
        p = self._settings.judge_provider or self._settings.provider
        return getattr(p, "value", str(p))

    @property
    def _model(self) -> str:
        return self._settings.judge_model or self._settings.model_name

    async def _unjudged(self, db, limit: int | None):
        stmt = (
            select(EvalTrace)
            .where(~select(EvalJudgement.id)
                   .where(EvalJudgement.trace_id == EvalTrace.id)
                   .exists())
            .order_by(EvalTrace.id)
        )
        if limit:
            stmt = stmt.limit(limit)
        return list((await db.execute(stmt)).scalars().all())

    async def run_batch(self, limit: int | None = None,
                        judge_run_id: str | None = None) -> dict:
        run_id = judge_run_id or uuid.uuid4().hex
        judged = skipped = 0
        async with self._sm() as db:
            traces = await self._unjudged(db, limit)

        for trace in traces:
            try:
                async with self._sm() as db:
                    chunks = list((await db.execute(
                        select(EvalRetrievedChunk)
                        .where(EvalRetrievedChunk.trace_id == trace.id)
                        .order_by(EvalRetrievedChunk.fused_rank)
                    )).scalars().all())

                    # bodies were nulled (eval_log_message_bodies=false) -> can't judge
                    if not trace.reply_text and not trace.query:
                        skipped += 1
                        continue

                    result = await self._judge.judge_trace(trace, chunks)
                    for m in result.metrics:
                        db.add(EvalJudgement(
                            trace_id=trace.id, metric=m.metric, score=m.score,
                            reasoning=m.reasoning, judge_provider=self._provider,
                            judge_model=self._model, judge_run_id=run_id,
                        ))
                    for lbl in result.chunk_labels:
                        db.add(EvalChunkLabel(
                            trace_id=trace.id, chunk_ref_id=lbl.chunk_ref_id,
                            relevance=lbl.relevance, reasoning=lbl.reasoning,
                            judge_provider=self._provider, judge_model=self._model,
                            judge_run_id=run_id,
                        ))
                    await db.commit()
                    judged += 1
            except Exception:  # noqa: BLE001 — one bad trace shouldn't stop the batch
                log.warning("judging trace %s failed", trace.id, exc_info=True)

        async with self._sm() as db:
            remaining = len(await self._unjudged(db, None))
        return {"judged": judged, "skipped": skipped, "remaining": remaining,
                "judge_run_id": run_id}

    async def status(self) -> dict:
        async with self._sm() as db:
            total = (await db.execute(
                select(func.count()).select_from(EvalTrace))).scalar_one()
            judged = (await db.execute(
                select(func.count(func.distinct(EvalJudgement.trace_id))))).scalar_one()
            rows = (await db.execute(
                select(EvalJudgement.metric, func.avg(EvalJudgement.score))
                .group_by(EvalJudgement.metric)
            )).all()
        avg = {m: (round(float(a), 4) if a is not None else None) for m, a in rows}
        return {"total_traces": total, "judged": judged,
                "unjudged": total - judged, "avg_scores": avg}
