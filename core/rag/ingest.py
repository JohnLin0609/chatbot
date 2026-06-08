"""Ingest curated documents into the vector store + document registry.

Chunking is per-type (see core/rag/chunkers): slides (.pptx) → one chunk per
slide; prose → spaCy sentence-grouping; token → fixed windows.
"""

import hashlib
import re
from datetime import datetime, timezone

from core.config import Settings
from core.documents.store import DocumentStore
from core.rag.chunkers import ChunkUnit, chunk_code, chunk_slides, chunk_text_doc
from core.rag.embeddings import EmbeddingService
from core.rag.pptx import parse_pptx
from core.rag.sparse import SparseEmbedder
from core.rag.vector_store import QdrantVectorStore, VectorPoint
from core.tokens.counter import TokenCounter


class SlideRangeError(ValueError):
    """skip_leading/skip_trailing would discard every slide in the deck."""


_WEEK_RE = re.compile(r"^[Ww](\d{1,2})")


def _lecture_from_filename(name: str | None) -> int | None:
    """Derive the lecture number from a `W##_…` filename so slides and code pair
    by week. `W14_例外處理.pptx` -> 14, `W05_條件判斷.py` -> 5, else None."""
    m = _WEEK_RE.match(name or "")
    return int(m.group(1)) if m else None


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _trim_slides(slides: list, skip_leading: int, skip_trailing: int) -> list:
    """Drop `skip_leading` slides from the front and `skip_trailing` from the
    back (e.g. cover / agenda / closing slides). Slide numbers are preserved on
    the kept slides so provenance still reflects the original deck position."""
    lead = max(0, skip_leading)
    trail = max(0, skip_trailing)
    end = len(slides) - trail
    return slides[lead:end] if end > lead else []


def _doc_id(title: str | None, source_hash: str, given: str | None) -> str:
    if given:
        return given
    return hashlib.sha256(f"{title or ''}\n{source_hash}".encode()).hexdigest()[:16]


class IngestService:
    def __init__(
        self,
        settings: Settings,
        embedding_service: EmbeddingService,
        vector_store: QdrantVectorStore,
        counter: TokenCounter,
        document_store: DocumentStore | None = None,
        sparse_embedder: SparseEmbedder | None = None,
    ) -> None:
        self._settings = settings
        self._embedding = embedding_service
        self._store = vector_store
        self._counter = counter
        self._docs = document_store
        self._sparse = sparse_embedder

    async def ingest_text(
        self,
        text: str,
        *,
        title: str | None = None,
        doc_type: str = "prose",
        metadata: dict | None = None,
        doc_id: str | None = None,
    ) -> tuple[str, int]:
        source_hash = _hash(text.encode())
        units = chunk_text_doc(doc_type, text, self._counter, self._settings)
        return await self._commit(units, title, doc_type, metadata, doc_id, source_hash)

    async def ingest_pptx(
        self,
        data: bytes,
        *,
        title: str | None = None,
        source_file: str | None = None,
        metadata: dict | None = None,
        doc_id: str | None = None,
        skip_leading: int = 0,
        skip_trailing: int = 0,
    ) -> tuple[str, int]:
        source_hash = _hash(data)
        slides = parse_pptx(data)
        kept = _trim_slides(slides, skip_leading, skip_trailing)
        if slides and not kept:
            raise SlideRangeError(
                f"skip_leading ({skip_leading}) + skip_trailing ({skip_trailing}) "
                f"would discard all {len(slides)} slides"
            )
        units = chunk_slides(kept, self._counter, self._settings)
        # lecture derives from the real filename (not the admin-editable title) so
        # pairing survives a renamed deck.
        src = source_file or title
        extra = {"content_type": "slide", "lecture": _lecture_from_filename(src),
                 "topic": None, "language": None, "source_file": src}
        return await self._commit(units, title, "slides", metadata, doc_id,
                                  source_hash, extra_fields=extra)

    async def ingest_code(
        self,
        text: str,
        *,
        title: str | None = None,
        source_file: str | None = None,
        topic: str | None = None,
        metadata: dict | None = None,
        doc_id: str | None = None,
    ) -> tuple[str, int]:
        source_hash = _hash(text.encode())
        units = chunk_code(text, self._counter, self._settings)
        src = source_file or title
        extra = {"content_type": "code", "lecture": _lecture_from_filename(src),
                 "topic": topic, "language": "python", "source_file": src}
        return await self._commit(units, title, "code", metadata, doc_id,
                                  source_hash, extra_fields=extra)

    async def _commit(
        self,
        units: list[ChunkUnit],
        title: str | None,
        doc_type: str,
        metadata: dict | None,
        doc_id: str | None,
        source_hash: str,
        extra_fields: dict | None = None,
    ) -> tuple[str, int]:
        doc_id = _doc_id(title, source_hash, doc_id)
        if not units:
            if self._docs:
                await self._docs.upsert(
                    doc_id, title=title, doc_type=doc_type, chunk_count=0,
                    source_hash=source_hash,
                )
            return doc_id, 0

        texts = [u.text for u in units]
        vectors = await self._embedding.embed(texts)
        sparse = self._sparse.embed_documents(texts) if self._sparse else None
        now = datetime.now(timezone.utc).isoformat()
        extra = extra_fields or {}
        points = [
            VectorPoint(
                doc_id=doc_id,
                chunk_index=u.ordinal,
                vector=vectors[i],
                text=u.text,
                source="curated",
                title=title,
                metadata={**(metadata or {}), **u.metadata},
                created_at=now,
                enabled=True,
                sparse={"indices": sparse[i].indices, "values": sparse[i].values}
                if sparse else None,
                **extra,
            )
            for i, u in enumerate(units)
        ]
        # Replace any prior chunks for this doc so a shorter re-ingest leaves no
        # stale tail, then upsert the fresh set.
        await self._store.delete_doc(doc_id)
        await self._store.upsert(points)
        if self._docs:
            await self._docs.upsert(
                doc_id, title=title, doc_type=doc_type, chunk_count=len(points),
                source_hash=source_hash,
            )
        return doc_id, len(points)
