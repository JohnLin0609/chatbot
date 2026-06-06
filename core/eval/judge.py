"""LLM-as-judge: reference-free scoring of captured traces.

Produces per-trace generation metrics (faithfulness, answer_relevance,
context_utilization) and per-retrieved-chunk relevance labels. All scores are 0–1.
Best-effort: a parse/LLM failure yields no rows for that trace, never raises.
"""

import json
import logging
from dataclasses import dataclass, field

log = logging.getLogger("eval.judge")

GEN_METRICS = ("faithfulness", "answer_relevance", "context_utilization")
# Metrics that require retrieved context; null for no-context (simple-tier) traces.
CONTEXT_METRICS = ("faithfulness", "context_utilization")

_GEN_SYSTEM = (
    "You are a strict evaluator of a RAG assistant. Score each metric from 0.0 to "
    "1.0 and give a one-sentence reason. Metrics:\n"
    "- faithfulness: is the ANSWER fully supported by the CONTEXT (no claims beyond "
    "it)? 1.0 = every claim grounded; 0.0 = contradicted/unsupported.\n"
    "- answer_relevance: does the ANSWER actually address the QUESTION? 1.0 = fully "
    "on-point; 0.0 = off-topic.\n"
    "- context_utilization: how much of the ANSWER's substance comes from the "
    "CONTEXT? 1.0 = grounded in it; 0.0 = ignores it.\n"
    'Reply with ONLY JSON: {"faithfulness":{"score":<0-1>,"reasoning":"..."},'
    '"answer_relevance":{"score":<0-1>,"reasoning":"..."},'
    '"context_utilization":{"score":<0-1>,"reasoning":"..."}}.'
)
_GEN_SYSTEM_NO_CONTEXT = (
    "You are a strict evaluator of an assistant reply. There was NO retrieved "
    "context for this turn. Score only answer_relevance from 0.0 to 1.0: does the "
    "ANSWER address the QUESTION? Give a one-sentence reason.\n"
    'Reply with ONLY JSON: {"answer_relevance":{"score":<0-1>,"reasoning":"..."}}.'
)
_CHUNK_SYSTEM = (
    "You judge whether each retrieved document chunk is relevant to answering the "
    "QUESTION. Score relevance 0.0 (irrelevant) to 1.0 (directly answers it) with a "
    "one-sentence reason, for every chunk by its index.\n"
    'Reply with ONLY JSON: {"chunks":[{"index":<int>,"relevance":<0-1>,'
    '"reasoning":"..."}, ...]}.'
)
_CORRECTNESS_SYSTEM = (
    "You compare a candidate ANSWER to a known-correct REFERENCE for a QUESTION. "
    "Score correctness 0.0 (wrong/contradictory) to 1.0 (fully matches the reference "
    "in substance — wording may differ) with a one-sentence reason.\n"
    'Reply with ONLY JSON: {"score":<0-1>,"reasoning":"..."}.'
)


def _extract_json(raw: str) -> dict:
    """Tolerant JSON parse: take the first balanced {...} object."""
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        pass
    start = raw.find("{")
    if start == -1:
        return {}
    depth = 0
    for i in range(start, len(raw)):
        if raw[i] == "{":
            depth += 1
        elif raw[i] == "}":
            depth -= 1
            if depth == 0:
                try:
                    return json.loads(raw[start : i + 1])
                except json.JSONDecodeError:
                    return {}
    return {}


def _clamp01(v) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return max(0.0, min(1.0, f))


@dataclass
class MetricScore:
    metric: str
    score: float | None
    reasoning: str | None


@dataclass
class ChunkLabel:
    chunk_ref_id: int
    relevance: float | None
    reasoning: str | None


@dataclass
class JudgementResult:
    metrics: list[MetricScore] = field(default_factory=list)
    chunk_labels: list[ChunkLabel] = field(default_factory=list)


class Judge:
    def __init__(self, chat_service, settings) -> None:
        self._chat = chat_service
        self._settings = settings

    async def judge_trace(self, trace, chunks) -> JudgementResult:
        """`trace` is an EvalTrace; `chunks` a list of EvalRetrievedChunk."""
        result = JudgementResult()
        has_context = bool(chunks) or bool(trace.knowledge_text)
        try:
            result.metrics = await self._judge_generation(trace, chunks, has_context)
        except Exception:  # noqa: BLE001 — best-effort
            log.warning("generation judging failed for trace %s", trace.id, exc_info=True)
        if chunks:
            try:
                result.chunk_labels = await self._judge_chunks(trace, chunks)
            except Exception:  # noqa: BLE001
                log.warning("chunk judging failed for trace %s", trace.id, exc_info=True)
        return result

    def _context_text(self, trace, chunks) -> str:
        if chunks:
            return "\n".join(
                f"[{i}] {c.chunk_text or ''}" for i, c in enumerate(chunks)
            )
        return trace.knowledge_text or ""

    async def _judge_generation(self, trace, chunks, has_context) -> list[MetricScore]:
        if has_context:
            system = _GEN_SYSTEM
            user = (
                f"QUESTION:\n{trace.query or ''}\n\n"
                f"CONTEXT:\n{self._context_text(trace, chunks)}\n\n"
                f"ANSWER:\n{trace.reply_text or ''}"
            )
            wanted = GEN_METRICS
        else:
            system = _GEN_SYSTEM_NO_CONTEXT
            user = f"QUESTION:\n{trace.query or ''}\n\nANSWER:\n{trace.reply_text or ''}"
            wanted = ("answer_relevance",)

        raw = await self._chat.generate_reply(
            "judge", [{"role": "system", "content": system},
                      {"role": "user", "content": user}]
        )
        data = _extract_json(raw)
        scores = []
        for metric in wanted:
            entry = data.get(metric) or {}
            scores.append(MetricScore(
                metric=metric,
                score=_clamp01(entry.get("score")),
                reasoning=entry.get("reasoning"),
            ))
        # context metrics are explicitly null when there was no context
        if not has_context:
            for metric in CONTEXT_METRICS:
                scores.append(MetricScore(metric=metric, score=None,
                                          reasoning="no retrieved context"))
        return scores

    async def judge_correctness(self, query: str, answer: str,
                                reference: str) -> MetricScore:
        """Score a generated answer against a reference answer (golden eval)."""
        user = (f"QUESTION:\n{query or ''}\n\nREFERENCE:\n{reference or ''}\n\n"
                f"ANSWER:\n{answer or ''}")
        raw = await self._chat.generate_reply(
            "judge", [{"role": "system", "content": _CORRECTNESS_SYSTEM},
                      {"role": "user", "content": user}]
        )
        data = _extract_json(raw)
        return MetricScore(
            metric="correctness",
            score=_clamp01(data.get("score")),
            reasoning=data.get("reasoning"),
        )

    async def _judge_chunks(self, trace, chunks) -> list[ChunkLabel]:
        listing = "\n".join(
            f"[{i}] {(c.chunk_text or '')[:1000]}" for i, c in enumerate(chunks)
        )
        user = f"QUESTION:\n{trace.query or ''}\n\nCHUNKS:\n{listing}"
        raw = await self._chat.generate_reply(
            "judge", [{"role": "system", "content": _CHUNK_SYSTEM},
                      {"role": "user", "content": user}]
        )
        data = _extract_json(raw)
        by_index = {}
        for item in data.get("chunks", []) or []:
            try:
                by_index[int(item.get("index"))] = item
            except (TypeError, ValueError):
                continue
        labels = []
        for i, c in enumerate(chunks):
            item = by_index.get(i, {})
            labels.append(ChunkLabel(
                chunk_ref_id=c.id,
                relevance=_clamp01(item.get("relevance")),
                reasoning=item.get("reasoning"),
            ))
        return labels
