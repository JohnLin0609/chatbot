"""Qdrant vector store wrapper (async)."""

import logging
import uuid
from dataclasses import dataclass, field

logger = logging.getLogger("rag.vector_store")

# Stable namespace so (doc_id, chunk_index) -> deterministic point id.
_POINT_NS = uuid.UUID("a3f1c2d4-0000-4000-8000-000000000001")


def chunk_point_id(doc_id, chunk_index) -> str:
    """Deterministic point id for a chunk — same scheme as VectorPoint.point_id."""
    return str(uuid.uuid5(_POINT_NS, f"{doc_id}:{chunk_index}"))

# Named dense vector in the collection (sparse name comes from settings).
DENSE = "dense"


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
    enabled: bool = True
    sparse: dict | None = None  # {"indices": [...], "values": [...]} when hybrid

    def point_id(self) -> str:
        return chunk_point_id(self.doc_id, self.chunk_index)

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
            "enabled": self.enabled,
        }


@dataclass
class Hit:
    text: str
    score: float  # fused RRF score from Qdrant (dense+sparse combined)
    title: str | None
    payload: dict
    rerank_score: float | None = None  # set by the reranker (complex tier)


class QdrantVectorStore:
    def __init__(
        self, url: str, collection: str, dim: int, sparse_vector_name: str = "text-sparse"
    ) -> None:
        from qdrant_client import AsyncQdrantClient

        # check_compatibility=False: tolerate a minor client/server version gap.
        self._client = AsyncQdrantClient(url=url, check_compatibility=False)
        self._collection = collection
        self._dim = dim
        self._sparse = sparse_vector_name

    async def ensure_collection(self) -> None:
        from qdrant_client.models import (
            Distance,
            Modifier,
            SparseVectorParams,
            VectorParams,
        )

        if await self._client.collection_exists(self._collection):
            return
        await self._client.create_collection(
            collection_name=self._collection,
            # Named dense vector + a BM25 sparse vector. Modifier.IDF is REQUIRED:
            # fastembed emits TF only; Qdrant supplies IDF from collection stats.
            vectors_config={DENSE: VectorParams(size=self._dim, distance=Distance.COSINE)},
            sparse_vectors_config={self._sparse: SparseVectorParams(modifier=Modifier.IDF)},
        )

    async def delete_doc(self, doc_id: str) -> None:
        from qdrant_client.models import FieldCondition, Filter, FilterSelector, MatchValue

        await self._client.delete(
            collection_name=self._collection,
            points_selector=FilterSelector(
                filter=Filter(must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))])
            ),
        )

    def _vectors(self, p: VectorPoint) -> dict:
        from qdrant_client.models import SparseVector

        vectors: dict = {DENSE: p.vector}
        if p.sparse is not None:
            vectors[self._sparse] = SparseVector(
                indices=p.sparse["indices"], values=p.sparse["values"]
            )
        return vectors

    async def upsert(self, points: list[VectorPoint]) -> None:
        from qdrant_client.models import PointStruct

        await self._client.upsert(
            collection_name=self._collection,
            points=[
                PointStruct(id=p.point_id(), vector=self._vectors(p), payload=p.payload())
                for p in points
            ],
        )

    async def set_payload(self, doc_id: str, payload: dict) -> None:
        """Patch payload on all points of a doc (e.g. flip `enabled`)."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        await self._client.set_payload(
            collection_name=self._collection,
            payload=payload,
            points=Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            ),
        )

    async def scroll_doc(self, doc_id: str) -> list[dict]:
        """Return a doc's chunks (payloads) ordered by chunk_index — for the
        chunk-inspection / visualiser API."""
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        points, _ = await self._client.scroll(
            collection_name=self._collection,
            scroll_filter=Filter(
                must=[FieldCondition(key="doc_id", match=MatchValue(value=doc_id))]
            ),
            limit=10000,
            with_payload=True,
            with_vectors=False,
        )
        payloads = [p.payload or {} for p in points]
        payloads.sort(key=lambda pl: pl.get("chunk_index", 0))
        return payloads

    def _filter(self, source: str | None, enabled: bool | None):
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        must = []
        if source is not None:
            must.append(FieldCondition(key="source", match=MatchValue(value=source)))
        if enabled is not None:
            must.append(FieldCondition(key="enabled", match=MatchValue(value=enabled)))
        return Filter(must=must) if must else None

    @staticmethod
    def _hits(points) -> list[Hit]:
        return [
            Hit(
                text=(r.payload or {}).get("text", ""),
                score=r.score,
                title=(r.payload or {}).get("title"),
                payload=r.payload or {},
            )
            for r in points
        ]

    async def search(
        self,
        vector: list[float],
        top_k: int,
        *,
        source: str | None = None,
        enabled: bool | None = None,
        score_threshold: float | None = None,
    ) -> list[Hit]:
        """Dense-only search (named 'dense' vector). Hybrid path uses hybrid_search."""
        try:
            response = await self._client.query_points(
                collection_name=self._collection,
                query=vector,
                using=DENSE,
                limit=top_k,
                query_filter=self._filter(source, enabled),
                score_threshold=score_threshold,
            )
        except Exception:  # noqa: BLE001 — missing collection / transient errors
            logger.exception("qdrant search failed")
            return []
        return self._hits(response.points)

    async def hybrid_search(
        self,
        dense: list[float],
        sparse: dict | None,
        top_k: int,
        *,
        source: str | None = None,
        enabled: bool | None = True,
        prefetch_limit: int = 50,
    ) -> list[Hit]:
        """Dense + BM25 sparse retrieval fused server-side with RRF. Falls back to
        dense-only when no sparse vector is supplied. Fault-tolerant (-> [])."""
        from qdrant_client.models import (
            Fusion,
            FusionQuery,
            Prefetch,
            SparseVector,
        )

        qfilter = self._filter(source, enabled)
        prefetch = [
            Prefetch(query=dense, using=DENSE, limit=prefetch_limit, filter=qfilter)
        ]
        if sparse is not None:
            prefetch.append(
                Prefetch(
                    query=SparseVector(indices=sparse["indices"], values=sparse["values"]),
                    using=self._sparse,
                    limit=prefetch_limit,
                    filter=qfilter,
                )
            )
        try:
            response = await self._client.query_points(
                collection_name=self._collection,
                prefetch=prefetch,
                query=FusionQuery(fusion=Fusion.RRF),
                limit=top_k,
                with_payload=True,
            )
        except Exception:  # noqa: BLE001 — missing collection / transient errors
            logger.exception("qdrant hybrid search failed")
            return []
        return self._hits(response.points)
