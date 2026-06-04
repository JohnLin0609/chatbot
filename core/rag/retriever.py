"""RagRetriever: embed a query (dense + BM25 sparse) and run hybrid search over
the curated, enabled knowledge, returning Hits. Degrades to dense-only when no
sparse embedder is configured."""

import logging

from core.config import Settings
from core.rag.embeddings import EmbeddingService
from core.rag.sparse import SparseEmbedder
from core.rag.vector_store import Hit, QdrantVectorStore

log = logging.getLogger("rag.retriever")


class RagRetriever:
    def __init__(
        self,
        vector_store: QdrantVectorStore,
        embedding_service: EmbeddingService,
        sparse_embedder: SparseEmbedder | None,
        settings: Settings,
    ) -> None:
        self._store = vector_store
        self._embedding = embedding_service
        self._sparse = sparse_embedder
        self._settings = settings

    async def retrieve(self, query: str, *, top_k: int) -> list[Hit]:
        try:
            dense = (await self._embedding.embed([query]))[0]
        except Exception:  # noqa: BLE001 — embedding failure -> no knowledge
            log.warning("query embedding failed; skipping retrieval", exc_info=True)
            return []
        sparse = None
        if self._sparse is not None:
            try:
                sv = self._sparse.embed_query(query)
                sparse = {"indices": sv.indices, "values": sv.values}
            except Exception:  # noqa: BLE001 — fall back to dense-only
                log.warning("sparse query embedding failed; dense-only", exc_info=True)
        return await self._store.hybrid_search(
            dense,
            sparse,
            top_k,
            source="curated",
            enabled=True,
            prefetch_limit=self._settings.rag_prefetch_limit,
        )
