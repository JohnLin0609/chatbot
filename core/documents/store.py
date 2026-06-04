"""DocumentStore: CRUD over the `documents` registry (Postgres source of truth
for the curated-doc list / UI). Chunks themselves live in Qdrant; toggling
`enabled` here is mirrored into the Qdrant payload by the caller so retrieval can
filter on it."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.persistence.models import Document


def _to_dict(d: Document) -> dict:
    return {
        "doc_id": d.doc_id,
        "title": d.title,
        "doc_type": d.doc_type,
        "enabled": d.enabled,
        "chunk_count": d.chunk_count,
        "source_hash": d.source_hash,
        "created_at": d.created_at.isoformat() if d.created_at else None,
        "updated_at": d.updated_at.isoformat() if d.updated_at else None,
    }


class DocumentStore:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sm = sessionmaker

    async def upsert(
        self,
        doc_id: str,
        *,
        title: str | None,
        doc_type: str,
        chunk_count: int,
        source_hash: str | None = None,
        enabled: bool = True,
    ) -> dict:
        async with self._sm() as db:
            row = await db.get(Document, doc_id)
            if row is None:
                row = Document(doc_id=doc_id, enabled=enabled)
                db.add(row)
            row.title = title
            row.doc_type = doc_type
            row.chunk_count = chunk_count
            row.source_hash = source_hash
            await db.commit()
            await db.refresh(row)
            return _to_dict(row)

    async def list(self) -> list[dict]:
        async with self._sm() as db:
            rows = (await db.execute(select(Document).order_by(Document.created_at))).scalars()
            return [_to_dict(r) for r in rows]

    async def get(self, doc_id: str) -> dict | None:
        async with self._sm() as db:
            row = await db.get(Document, doc_id)
            return _to_dict(row) if row else None

    async def set_enabled(self, doc_id: str, enabled: bool) -> dict | None:
        async with self._sm() as db:
            row = await db.get(Document, doc_id)
            if row is None:
                return None
            row.enabled = enabled
            await db.commit()
            await db.refresh(row)
            return _to_dict(row)
