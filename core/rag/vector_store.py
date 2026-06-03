"""Qdrant vector store wrapper (async)."""

import logging
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger("rag.vector_store")

# Stable namespace so (doc_id, chunk_index) -> deterministic point id.
_POINT_NS = uuid.UUID("a3f1c2d4-0000-4000-8000-000000000001")


@dataclass
class VectorPoint:
    doc_id: str
    chunk_index: int
    vector: list[float]
    text: str
    source: str = "curated"
    title: str | None = None
    metadata: dict = field(default_factory=dict)
    user_key: str | None = None
    channel_id: str | None = None
    created_at: str | None = None

    def point_id(self) -> str:
        return str(uuid.uuid5(_POINT_NS, f"{self.doc_id}:{self.chunk_index}"))

    def payload(self) -> dict:
        return {
            "source": self.source,
            "text": self.text,
            "doc_id": self.doc_id,
            "chunk_index": self.chunk_index,
            "title": self.title,
            "metadata": self.metadata,
            "user_key": self.user_key,
            "channel_id": self.channel_id,
            "created_at": self.created_at,
        }


@dataclass
class Hit:
    text: str
    score: float
    title: str | None
    payload: dict


class QdrantVectorStore:
    def __init__(self, url: str, collection: str, dim: int) -> None:
        from qdrant_client import AsyncQdrantClient

        # check_compatibility=False: tolerate a minor client/server version gap.
        self._client = AsyncQdrantClient(url=url, check_compatibility=False)
        self._collection = collection
        self._dim = dim

    async def ensure_collection(self) -> None:
        from qdrant_client.models import Distance, VectorParams

        if await self._client.collection_exists(self._collection):
            return
        await self._client.create_collection(
            collection_name=self._collection,
            vectors_config=VectorParams(size=self._dim, distance=Distance.COSINE),
        )

    async def delete_doc(self, doc_id: str) -> None:
        from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

        await self._client.delete(
            collection_name=self._collection,
            points_selector=FilterSelector(
                filter=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))])
            ),
        )

    async def upsert(self, points: list[VectorPoint]) -> None:
        from qdrant_client.models import PointStruct

        await self._client.upsert(
            collection_name=self._collection,
            points=[
                PointStruct(id=p.point_id(), vector=p.vector, payload=p.payload())
                for p in points
            ],
        )

    async def search(
        self,
        vector: list[float],
        top_k: int,
        *,
        source: str | None = None,
        score_threshold: float | None = None,
    ) -> list[Hit]:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        query_filter = None
        if source is not None:
            query_filter = Filter(
                must=[FieldCondition(key="source", match=MatchValue(value=source))]
            )
        try:
            response = await self._client.query_points(
                collection_name=self._collection,
                query=vector,
                limit=top_k,
                query_filter=query_filter,
                score_threshold=score_threshold,
            )
        except Exception:  # noqa: BLE001 — missing collection / transient errors
            logger.exception("qdrant search failed")
            return []

        return [
            Hit(
                text=(r.payload or {}).get("text", ""),
                score=r.score,
                title=(r.payload or {}).get("title"),
                payload=r.payload or {},
            )
            for r in response.points
        ]
