"""Ingest curated documents into the vector store + document registry.

Chunking is per-type (see core/rag/chunkers): slides (.pptx) → one chunk per
slide; prose → spaCy sentence-grouping; token → fixed windows.
"""

import hashlib
from datetime import datetime, timezone

from core.config import Settings
from core.documents.store import DocumentStore
from core.rag.chunkers import ChunkUnit, chunk_slides, chunk_text_doc
from core.rag.embeddings import EmbeddingService
from core.rag.pptx import parse_pptx
from core.rag.vector_store import QdrantVectorStore, VectorPoint
from core.tokens.counter import TokenCounter


def _hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


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
    ) -> None:
        self._settings = settings
        self._embedding = embedding_service
        self._store = vector_store
        self._counter = counter
        self._docs = document_store

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
        metadata: dict | None = None,
        doc_id: str | None = None,
    ) -> tuple[str, int]:
        source_hash = _hash(data)
        slides = parse_pptx(data)
        units = chunk_slides(slides, self._counter, self._settings)
        return await self._commit(units, title, "slides", metadata, doc_id, source_hash)

    async def _commit(
        self,
        units: list[ChunkUnit],
        title: str | None,
        doc_type: str,
        metadata: dict | None,
        doc_id: str | None,
        source_hash: str,
    ) -> tuple[str, int]:
        doc_id = _doc_id(title, source_hash, doc_id)
        if not units:
            if self._docs:
                await self._docs.upsert(
                    doc_id, title=title, doc_type=doc_type, chunk_count=0,
                    source_hash=source_hash,
                )
            return doc_id, 0

        vectors = await self._embedding.embed([u.text for u in units])
        now = datetime.now(timezone.utc).isoformat()
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
