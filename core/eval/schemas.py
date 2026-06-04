"""Structured retrieval trace passed from the pipeline to the eval logger."""

from dataclasses import dataclass, field


@dataclass
class CandidateRecord:
    """One retrieved candidate with its scores/ranks and final disposition."""

    doc_id: str | None
    chunk_index: int | None
    point_id: str | None
    title: str | None
    chunk_text: str | None
    fused_score: float | None
    fused_rank: int | None
    rerank_score: float | None = None
    final_rank: int | None = None
    included: bool = False


@dataclass
class RetrievalTrace:
    tier: str  # simple | medium | complex
    reranked: bool = False
    candidates: list[CandidateRecord] = field(default_factory=list)
