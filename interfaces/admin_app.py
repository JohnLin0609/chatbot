"""Admin/management HTTP app — curated knowledge ingestion.

Run:  uvicorn interfaces.admin_app:app --port 8754

Kept separate from the chat gateway (http_app): ingestion holds the vector
store / embedding client directly, with a different security/ops boundary.
"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from pydantic import BaseModel, Field

from core.config import get_settings
from core.rag.embeddings import build_embedding_service
from core.rag.ingest import IngestService
from core.rag.vector_store import QdrantVectorStore
from core.tokens.counter import TokenCounter


class IngestRequest(BaseModel):
    text: str = Field(..., min_length=1)
    title: str | None = None
    metadata: dict | None = None
    doc_id: str | None = None


class IngestResponse(BaseModel):
    doc_id: str
    chunks_ingested: int


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    embedding = build_embedding_service(settings)
    store = QdrantVectorStore(
        settings.qdrant_url, settings.qdrant_collection, settings.embedding_dim
    )
    await store.ensure_collection()
    app.state.ingest = IngestService(
        settings, embedding, store, TokenCounter(settings.tiktoken_encoding)
    )
    yield


app = FastAPI(title="Chatbot Admin", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest) -> IngestResponse:
    doc_id, count = await app.state.ingest.ingest(
        text=request.text, title=request.title,
        metadata=request.metadata, doc_id=request.doc_id,
    )
    return IngestResponse(doc_id=doc_id, chunks_ingested=count)
