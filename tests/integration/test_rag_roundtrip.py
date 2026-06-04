"""RAG ingest -> hybrid search round-trip over real Qdrant + real OpenAI
embeddings (+ fastembed BM25 if available).

Requires `docker compose up -d qdrant` and a valid OPENAI_API_KEY.
Run with: pytest -m integration. Skips if unavailable.
"""

import uuid

import pytest

from core.config import get_settings
from core.rag.embeddings import build_embedding_service
from core.rag.ingest import IngestService
from core.rag.sparse import build_sparse_embedder
from core.rag.vector_store import QdrantVectorStore
from core.tokens.counter import TokenCounter

pytestmark = pytest.mark.integration


async def test_ingest_then_hybrid_search():
    settings = get_settings()
    collection = f"itest_{uuid.uuid4().hex[:8]}"  # throwaway

    try:
        embedding = build_embedding_service(settings)
        store = QdrantVectorStore(
            settings.qdrant_url, collection, settings.embedding_dim,
            settings.rag_sparse_vector_name,
        )
        await store.ensure_collection()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"qdrant/openai not available: {exc}")

    sparse = build_sparse_embedder(settings)
    ingest = IngestService(
        settings, embedding, store, TokenCounter(settings.tiktoken_encoding),
        sparse_embedder=sparse,
    )
    try:
        _doc_id, n = await ingest.ingest_text(
            "Customers can request a refund within 30 days of purchase. "
            "Refunds are processed back to the original payment method.",
            title="Refund Policy",
            doc_type="token",
        )
        assert n >= 1

        # Dense search
        qvec = (await embedding.embed(["how long to get my money back?"]))[0]
        hits = await store.search(qvec, top_k=3, source="curated", enabled=True)
        assert hits and any("refund" in h.text.lower() for h in hits)

        # Hybrid (dense + BM25 sparse + RRF) — only if fastembed is available
        if sparse is not None:
            svec = sparse.embed_query("refund window days")
            hhits = await store.hybrid_search(
                qvec, {"indices": svec.indices, "values": svec.values},
                top_k=3, source="curated", enabled=True,
            )
            assert hhits and any("refund" in h.text.lower() for h in hhits)
    finally:
        await store._client.delete_collection(collection)
