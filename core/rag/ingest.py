"""Ingest curated documents into the vector store."""

import hashlib
from datetime import datetime, timezone

from core.config import Settings
from core.rag.chunking import chunk_text
from core.rag.embeddings import EmbeddingService
from core.rag.vector_store import QdrantVectorStore, VectorPoint
from core.tokens.counter import TokenCounter


def _doc_id(title: str | None, text: str, given: str | None) -> str:
    if given:
        return given
    digest = hashlib.sha256(f"{title or ''}\n{text}".encode()).hexdigest()
    return digest[:16]


class IngestService:
    def __init__(
        self,
        settings: Settings,
        embedding_service: EmbeddingService,
        vector_store: QdrantVectorStore,
        counter: TokenCounter,
    ) -> None:
        self._settings = settings
        self._embedding = embedding_service
        self._store = vector_store
        self._counter = counter

    async def ingest(
        self,
        text: str,
        title: str | None = None,
        metadata: dict | None = None,
        doc_id: str | None = None,
    ) -> tuple[str, int]:
        """Chunk -> embed -> upsert. Returns (doc_id, chunks_ingested)."""
        doc_id = _doc_id(title, text, doc_id)
        chunks = chunk_text(
            self._counter, text,
            self._settings.ingest_chunk_tokens, self._settings.ingest_chunk_overlap,
        )
        if not chunks:
            return doc_id, 0

        vectors = await self._embedding.embed(chunks)
        now = datetime.now(timezone.utc).isoformat()
        points = [
            VectorPoint(
                doc_id=doc_id, chunk_index=i, vector=vectors[i], text=chunk,
                source="curated", title=title, metadata=metadata or {}, created_at=now,
            )
            for i, chunk in enumerate(chunks)
        ]
        # Replace any prior chunks for this doc so a shorter re-ingest leaves no
        # stale tail, then upsert the fresh set.
        await self._store.delete_doc(doc_id)
        await self._store.upsert(points)
        return doc_id, len(points)
