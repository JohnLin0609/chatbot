"""BM25 sparse embeddings for hybrid retrieval.

fastembed's Bm25 emits **term frequencies** only; the real IDF is computed by
Qdrant at query time from collection statistics (the collection's sparse vector
must be configured with `Modifier.IDF`). CJK text must be word-segmented first
(fastembed's default tokeniser is whitespace/punctuation based and useless for
Chinese), so `tokenize_for_bm25` runs jieba and is applied identically at ingest
and query time.
"""

import logging
from dataclasses import dataclass

from core.config import Settings

log = logging.getLogger("rag.sparse")


@dataclass
class SparseVec:
    indices: list[int]
    values: list[float]


def tokenize_for_bm25(text: str) -> str:
    """Word-segment (jieba handles CJK and keeps latin tokens), space-joined."""
    import jieba

    return " ".join(t for t in jieba.cut(text) if t.strip())


class SparseEmbedder:
    """Wraps fastembed Bm25, applying jieba segmentation on both sides."""

    def __init__(self, model_name: str = "Qdrant/bm25") -> None:
        from fastembed import SparseTextEmbedding

        self._model = SparseTextEmbedding(model_name=model_name)

    def embed_documents(self, texts: list[str]) -> list[SparseVec]:
        pre = [tokenize_for_bm25(t) for t in texts]
        return [
            SparseVec(indices=list(e.indices), values=list(e.values))
            for e in self._model.embed(pre)
        ]

    def embed_query(self, text: str) -> SparseVec:
        pre = tokenize_for_bm25(text)
        e = next(iter(self._model.query_embed(pre)))
        return SparseVec(indices=list(e.indices), values=list(e.values))


def build_sparse_embedder(settings: Settings) -> SparseEmbedder | None:
    """Build the BM25 sparse embedder, or None when disabled / fastembed absent
    (the system then degrades to dense-only retrieval)."""
    if not settings.rag_sparse_enabled:
        return None
    try:
        return SparseEmbedder()
    except Exception:  # noqa: BLE001 — optional dependency / model download failure
        log.warning("fastembed unavailable; hybrid retrieval falls back to dense-only")
        return None
