"""GoldenRunner: re-run retrieval for each golden query, score retrieval metrics
vs the golden relevant set, generate an answer and judge it against the reference.

Stores one eval_golden_run + an eval_golden_result per query. Always retrieves
(the classifier is bypassed — golden queries are knowledge-seeking).
"""

import logging

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from core.eval import metrics as M
from core.persistence import repository as repo
from core.persistence.models import (
    EvalGoldenQuery,
    EvalGoldenResult,
    EvalGoldenRun,
)

log = logging.getLogger("eval.golden_runner")


def _format_knowledge(chunks: list[dict]) -> str:
    lines = []
    for i, c in enumerate(chunks, start=1):
        title = c.get("title") or "untitled"
        lines.append(f"[{i}] ({title}) {c.get('text', '')}")
    return "\n".join(lines)


def _mean(values: list) -> float | None:
    nums = [v for v in values if v is not None]
    return round(sum(nums) / len(nums), 4) if nums else None


class GoldenRunner:
    def __init__(self, sessionmaker, retriever, reranker, chat, judge, settings) -> None:
        self._sm = sessionmaker
        self._retriever = retriever
        self._reranker = reranker
        self._chat = chat
        self._judge = judge
        self._settings = settings

    @property
    def _provider(self) -> str:
        p = self._settings.provider
        return getattr(p, "value", str(p))

    @property
    def _judge_model(self) -> str:
        return self._settings.judge_model or self._settings.model_name

    async def _ranked(self, query: str):
        """Return (ranked_keys, hits-as-dicts) — the system's hybrid+rerank ranking."""
        cands = await self._retriever.retrieve(
            query, top_k=self._settings.golden_eval_candidates)
        if self._reranker is not None and cands:
            cands = await self._reranker.rerank(query, list(cands), len(cands))
        ranked, dicts = [], []
        for h in cands:
            p = h.payload or {}
            key = (p.get("doc_id"), p.get("chunk_index"))
            ranked.append(key)
            dicts.append({"doc_id": p.get("doc_id"), "chunk_index": p.get("chunk_index"),
                          "title": h.title, "text": h.text})
        return ranked, dicts

    async def run(self, k_values: list[int] | None = None) -> dict:
        ks = k_values or self._settings.golden_eval_k_values
        # resolve the system persona once (reflects the live override)
        async with self._sm() as db:
            system_prompt = await repo.get_app_setting(db, "system_prompt")
            queries = (await db.execute(
                select(EvalGoldenQuery)
                .options(selectinload(EvalGoldenQuery.relevant_chunks))
            )).scalars().all()
            golden = [(q.id, q.query, q.reference_answer,
                       {(c.doc_id, c.chunk_index): c.relevance for c in q.relevant_chunks})
                      for q in queries]
        persona = system_prompt or self._settings.system_prompt

        async with self._sm() as db:
            run = EvalGoldenRun(
                k_values=ks, num_queries=len(golden), model=self._settings.model_name,
                provider=self._provider, judge_model=self._judge_model,
            )
            db.add(run)
            await db.flush()
            run_id = run.id

            acc: dict = {"recall": {}, "precision": {}, "ndcg": {}, "hit_rate": {},
                         "mrr": [], "correctness": []}
            for qid, query, reference, gold in golden:
                try:
                    ranked, dicts = await self._ranked(query)
                    mtr = M.compute_retrieval_metrics(ranked, gold, ks)
                    rel = {k for k, g in gold.items() if g and g > 0}
                    retrieved = [
                        {**d, "rank": i, "relevant": (d["doc_id"], d["chunk_index"]) in rel}
                        for i, d in enumerate(dicts)
                    ]

                    answer = correctness = reasoning = None
                    if reference:
                        top = dicts[: self._settings.rag_complex_top_k]
                        messages = [
                            {"role": "system", "content": persona},
                            {"role": "system",
                             "content": f"Relevant knowledge:\n{_format_knowledge(top)}"},
                            {"role": "user", "content": query},
                        ]
                        answer = await self._chat.generate_reply("golden", messages)
                        c = await self._judge.judge_correctness(query, answer, reference)
                        correctness, reasoning = c.score, c.reasoning

                    db.add(EvalGoldenResult(
                        run_id=run_id, golden_query_id=qid, retrieved=retrieved,
                        metrics=mtr, generated_answer=answer, correctness=correctness,
                        correctness_reasoning=reasoning,
                    ))
                    # accumulate for the aggregate
                    for name in ("recall", "precision", "ndcg", "hit_rate"):
                        for k in ks:
                            acc[name].setdefault(str(k), []).append(mtr[name][str(k)])
                    acc["mrr"].append(mtr["mrr"])
                    if correctness is not None:
                        acc["correctness"].append(correctness)
                except Exception:  # noqa: BLE001 — one query shouldn't abort the run
                    log.warning("golden eval failed for query %s", qid, exc_info=True)

            aggregate = {
                name: {k: _mean(v) for k, v in acc[name].items()}
                for name in ("recall", "precision", "ndcg", "hit_rate")
            }
            aggregate["mrr"] = _mean(acc["mrr"])
            aggregate["correctness"] = _mean(acc["correctness"])
            run.aggregate = aggregate
            await db.commit()

        return {"run_id": run_id, "num_queries": len(golden),
                "k_values": ks, "aggregate": aggregate}

    async def latest_run(self) -> dict | None:
        async with self._sm() as db:
            run = (await db.execute(
                select(EvalGoldenRun).order_by(EvalGoldenRun.id.desc()).limit(1)
            )).scalar_one_or_none()
            if run is None:
                return None
            results = (await db.execute(
                select(EvalGoldenResult).where(EvalGoldenResult.run_id == run.id)
                .order_by(EvalGoldenResult.id)
            )).scalars().all()
            return {
                "run_id": run.id,
                "created_at": run.created_at.isoformat() if run.created_at else None,
                "k_values": run.k_values, "num_queries": run.num_queries,
                "aggregate": run.aggregate,
                "results": [
                    {"golden_query_id": r.golden_query_id, "metrics": r.metrics,
                     "correctness": r.correctness,
                     "correctness_reasoning": r.correctness_reasoning,
                     "generated_answer": r.generated_answer}
                    for r in results
                ],
            }
