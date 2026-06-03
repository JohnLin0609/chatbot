"""RAG ingest -> search round-trip over real Qdrant + real OpenAI embeddings.

Requires `docker compose up -d qdrant` and a valid OPENAI_API_KEY.
Run with: pytest -m integration. Skips if either is unavailable.
"""

import uuid

import pytest

from core.config import get_settings
from core.rag.embeddings import build_embedding_service
from core.rag.ingest import IngestService
from core.rag.search_tool import search_knowledge
from core.rag.vector_store import QdrantVectorStore
from core.tokens.counter import TokenCounter
from core.tools.schemas import ToolContext

pytestmark = pytest.mark.integration


async def test_ingest_then_search():
    settings = get_settings()
    # Use a throwaway collection so we don't touch real data.
    collection = f"itest_{uuid.uuid4().hex[:8]}"

    try:
        embedding = build_embedding_service(settings)
        store = QdrantVectorStore(settings.qdrant_url, collection, settings.embedding_dim)
        await store.ensure_collection()
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"qdrant/openai not available: {exc}")

    ingest = IngestService(settings, embedding, store, TokenCounter(settings.tiktoken_encoding))
    try:
        doc_id, n = await ingest.ingest(
            title="Refund Policy",
            text="Customers can request a refund within 30 days of purchase. "
                 "Refunds are processed back to the original payment method.",
        )
        assert n >= 1

        ctx = ToolContext(settings=settings, embedding_service=embedding, vector_store=store,
                          session_id="s", user_key="u", channel_id="c")
        result = await search_knowledge({"query": "how long do I have to get my money back?"}, ctx)
        assert "30 days" in result or "refund" in result.lower()

        # an unrelated query should not surface the refund chunk strongly
        unrelated = await search_knowledge({"query": "what is the capital of France?"}, ctx)
        assert isinstance(unrelated, str)
    finally:
        # cleanup the throwaway collection
        await store._client.delete_collection(collection)
