"""GoldenStore: CRUD over the golden eval set (queries + their relevant chunks).

Wraps a sessionmaker and owns its transactions, like DocumentStore.
"""

from __future__ import annotations

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import async_sessionmaker
from sqlalchemy.orm import selectinload

from core.persistence.models import EvalGoldenQuery, EvalGoldenRelevantChunk


def _chunk_dict(c: EvalGoldenRelevantChunk) -> dict:
    return {"doc_id": c.doc_id, "chunk_index": c.chunk_index, "relevance": c.relevance}


def _query_dict(q: EvalGoldenQuery) -> dict:
    return {
        "id": q.id,
        "query": q.query,
        "reference_answer": q.reference_answer,
        "notes": q.notes,
        "created_at": q.created_at.isoformat() if q.created_at else None,
        "relevant_chunks": [_chunk_dict(c) for c in q.relevant_chunks],
    }


class GoldenStore:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sm = sessionmaker

    async def _add_chunks(self, db, query_id: int, chunks: list[dict]) -> None:
        for ch in chunks or []:
            db.add(EvalGoldenRelevantChunk(
                golden_query_id=query_id,
                doc_id=ch.get("doc_id"),
                chunk_index=ch.get("chunk_index"),
                relevance=int(ch.get("relevance", 1) or 1),
            ))

    async def create(self, *, query: str, reference_answer: str | None = None,
                     notes: str | None = None, relevant_chunks: list[dict] | None = None) -> dict:
        async with self._sm() as db:
            row = EvalGoldenQuery(query=query, reference_answer=reference_answer, notes=notes)
            db.add(row)
            await db.flush()
            await self._add_chunks(db, row.id, relevant_chunks or [])
            await db.commit()
            return await self.get(row.id)

    async def list(self) -> list[dict]:
        async with self._sm() as db:
            rows = (await db.execute(
                select(EvalGoldenQuery)
                .options(selectinload(EvalGoldenQuery.relevant_chunks))
                .order_by(EvalGoldenQuery.id)
            )).scalars().all()
            return [_query_dict(q) for q in rows]

    async def get(self, query_id: int) -> dict | None:
        async with self._sm() as db:
            row = (await db.execute(
                select(EvalGoldenQuery)
                .options(selectinload(EvalGoldenQuery.relevant_chunks))
                .where(EvalGoldenQuery.id == query_id)
            )).scalar_one_or_none()
            return _query_dict(row) if row else None

    async def update(self, query_id: int, *, query: str | None = None,
                     reference_answer: str | None = None, notes: str | None = None,
                     relevant_chunks: list[dict] | None = None) -> dict | None:
        async with self._sm() as db:
            row = await db.get(EvalGoldenQuery, query_id)
            if row is None:
                return None
            if query is not None:
                row.query = query
            row.reference_answer = reference_answer
            row.notes = notes
            if relevant_chunks is not None:
                await db.execute(delete(EvalGoldenRelevantChunk).where(
                    EvalGoldenRelevantChunk.golden_query_id == query_id))
                await self._add_chunks(db, query_id, relevant_chunks)
            await db.commit()
        return await self.get(query_id)

    async def set_relevant_chunks(self, query_id: int, chunks: list[dict]) -> dict | None:
        async with self._sm() as db:
            if await db.get(EvalGoldenQuery, query_id) is None:
                return None
            await db.execute(delete(EvalGoldenRelevantChunk).where(
                EvalGoldenRelevantChunk.golden_query_id == query_id))
            await self._add_chunks(db, query_id, chunks)
            await db.commit()
        return await self.get(query_id)

    async def delete(self, query_id: int) -> bool:
        async with self._sm() as db:
            row = await db.get(EvalGoldenQuery, query_id)
            if row is None:
                return False
            await db.delete(row)  # cascade removes relevant chunks
            await db.commit()
            return True
