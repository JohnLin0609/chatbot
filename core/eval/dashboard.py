"""DashboardStore: read-only aggregation over the eval tables for the admin
dashboard. No writes, no migration — pure reporting."""

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.eval import metrics as M
from core.persistence.models import (
    EvalChunkLabel,
    EvalGoldenQuery,
    EvalGoldenRun,
    EvalJudgement,
    EvalRetrievedChunk,
    EvalTrace,
    LlmCall,
    MessageFeedback,
)

GEN_METRICS = ("faithfulness", "answer_relevance", "context_utilization")


def _f(v) -> float | None:
    return round(float(v), 4) if v is not None else None


def _iso(dt):
    return dt.isoformat() if dt else None


class DashboardStore:
    def __init__(self, sessionmaker: async_sessionmaker, settings) -> None:
        self._sm = sessionmaker
        self._settings = settings

    async def summary(self, k_values: list[int] | None = None) -> dict:
        ks = k_values or self._settings.golden_eval_k_values
        async with self._sm() as db:
            return {
                "overview": await self._overview(db),
                "generation": await self._generation_by_run(db),
                "retrieval": await self._retrieval_by_run(db, ks),
                "cost": await self._cost_by_day(db),
                "golden": await self._golden_history(db),
                "k_values": ks,
            }

    # ----------------------------------------------------------------- overview
    async def _overview(self, db) -> dict:
        async def count(stmt):
            return (await db.execute(stmt)).scalar_one()

        traces = await count(select(func.count()).select_from(EvalTrace))
        judged = await count(select(func.count(func.distinct(EvalJudgement.trace_id))))
        golden_q = await count(select(func.count()).select_from(EvalGoldenQuery))
        up = await count(select(func.count()).where(MessageFeedback.rating == 1))
        down = await count(select(func.count()).where(MessageFeedback.rating == -1))
        calls = await count(select(func.count()).select_from(LlmCall))
        return {"traces": traces, "judged_traces": judged, "golden_queries": golden_q,
                "feedback_up": up, "feedback_down": down, "llm_calls": calls}

    # -------------------------------------------------------------- generation
    async def _generation_by_run(self, db) -> dict:
        rows = (await db.execute(
            select(EvalJudgement.judge_run_id, EvalJudgement.metric,
                   func.avg(EvalJudgement.score), func.min(EvalJudgement.created_at))
            .where(EvalJudgement.metric.in_(GEN_METRICS))
            .group_by(EvalJudgement.judge_run_id, EvalJudgement.metric)
        )).all()
        runs: dict = defaultdict(lambda: {"at": None, "scores": {}})
        for run_id, metric, avg, at in rows:
            runs[run_id]["scores"][metric] = _f(avg)
            if runs[run_id]["at"] is None or (at and at < runs[run_id]["at"]):
                runs[run_id]["at"] = at
        series = sorted(
            ({"run": rid, "at": _iso(v["at"]), **{m: v["scores"].get(m) for m in GEN_METRICS}}
             for rid, v in runs.items()),
            key=lambda r: r["at"] or "",
        )
        # overall current means
        overall_rows = (await db.execute(
            select(EvalJudgement.metric, func.avg(EvalJudgement.score))
            .where(EvalJudgement.metric.in_(GEN_METRICS))
            .group_by(EvalJudgement.metric)
        )).all()
        current = {m: _f(a) for m, a in overall_rows}
        return {"series": series, "current": current}

    # --------------------------------------------------------------- retrieval
    async def _retrieval_by_run(self, db, ks: list[int]) -> dict:
        thr = self._settings.dashboard_relevance_threshold
        labels = (await db.execute(
            select(EvalChunkLabel.judge_run_id, EvalChunkLabel.trace_id,
                   EvalChunkLabel.chunk_ref_id, EvalChunkLabel.relevance)
        )).all()
        if not labels:
            return {"series": [], "current": None}
        # (run, trace) -> {chunk_ref_id: relevance}
        rel_by: dict = defaultdict(dict)
        trace_ids = set()
        for run, trace, cref, rel in labels:
            rel_by[(run, trace)][cref] = rel or 0.0
            trace_ids.add(trace)
        # ranking per trace (final_rank else fused_rank)
        chunks = (await db.execute(
            select(EvalRetrievedChunk.trace_id, EvalRetrievedChunk.id,
                   EvalRetrievedChunk.fused_rank, EvalRetrievedChunk.final_rank)
            .where(EvalRetrievedChunk.trace_id.in_(trace_ids))
        )).all()
        order: dict = defaultdict(list)
        for trace, cid, fr, finr in chunks:
            rank = finr if finr is not None else (fr if fr is not None else 1_000_000)
            order[trace].append((rank, cid))
        ranked_keys = {t: [cid for _, cid in sorted(v)] for t, v in order.items()}

        # judge_run timestamp (min created_at across that run's labels)
        run_at = dict((await db.execute(
            select(EvalChunkLabel.judge_run_id, func.min(EvalChunkLabel.created_at))
            .group_by(EvalChunkLabel.judge_run_id)
        )).all())

        per_run: dict = defaultdict(lambda: {"precision": defaultdict(list),
                                             "ndcg": defaultdict(list),
                                             "hit_rate": defaultdict(list), "mrr": []})
        for (run, trace), labelmap in rel_by.items():
            ranked = ranked_keys.get(trace, [])
            if not ranked:
                continue
            binary = {k: (v if v >= thr else 0.0) for k, v in labelmap.items()}
            for k in ks:
                per_run[run]["precision"][k].append(M.precision_at_k(ranked, binary, k))
                per_run[run]["hit_rate"][k].append(M.hit_rate_at_k(ranked, binary, k))
                per_run[run]["ndcg"][k].append(M.ndcg_at_k(ranked, labelmap, k))
            per_run[run]["mrr"].append(M.mrr(ranked, binary))

        def mean(xs):
            ys = [x for x in xs if x is not None]
            return _f(sum(ys) / len(ys)) if ys else None

        series = []
        for run, acc in per_run.items():
            series.append({
                "run": run, "at": _iso(run_at.get(run)),
                "precision": {str(k): mean(acc["precision"][k]) for k in ks},
                "ndcg": {str(k): mean(acc["ndcg"][k]) for k in ks},
                "hit_rate": {str(k): mean(acc["hit_rate"][k]) for k in ks},
                "mrr": mean(acc["mrr"]),
            })
        series.sort(key=lambda r: r["at"] or "")
        return {"series": series, "current": series[-1] if series else None}

    # ------------------------------------------------------------- cost / latency
    async def _cost_by_day(self, db) -> dict:
        day = func.date(LlmCall.created_at)
        by_day = (await db.execute(
            select(day, func.count(), func.sum(LlmCall.prompt_tokens),
                   func.sum(LlmCall.completion_tokens), func.avg(LlmCall.latency_ms))
            .group_by(day).order_by(day)
        )).all()
        series = [
            {"day": str(d), "calls": c, "prompt_tokens": int(pt or 0),
             "completion_tokens": int(ct or 0), "avg_latency_ms": _f(lat)}
            for d, c, pt, ct, lat in by_day
        ]
        types = (await db.execute(
            select(LlmCall.call_type, func.count(),
                   func.sum(LlmCall.prompt_tokens), func.sum(LlmCall.completion_tokens),
                   func.avg(LlmCall.latency_ms))
            .group_by(LlmCall.call_type).order_by(LlmCall.call_type)
        )).all()
        by_call_type = [
            {"call_type": t, "calls": c, "tokens": int((pt or 0) + (ct or 0)),
             "avg_latency_ms": _f(lat)}
            for t, c, pt, ct, lat in types
        ]
        totals = {
            "calls": sum(s["calls"] for s in series),
            "tokens": sum(s["prompt_tokens"] + s["completion_tokens"] for s in series),
        }
        return {"series": series, "by_call_type": by_call_type, "totals": totals}

    # ----------------------------------------------------------------- golden
    async def _golden_history(self, db) -> dict:
        runs = (await db.execute(
            select(EvalGoldenRun).order_by(EvalGoldenRun.id)
        )).scalars().all()
        series = [
            {"run_id": r.id, "at": _iso(r.created_at), "num_queries": r.num_queries,
             "aggregate": r.aggregate}
            for r in runs
        ]
        return {"series": series, "current": series[-1] if series else None}
