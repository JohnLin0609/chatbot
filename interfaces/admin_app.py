"""Admin/management HTTP app — curated knowledge ingestion + document management.

Run:  uvicorn interfaces.admin_app:app --port 8754

Kept separate from the chat gateway (http_app): ingestion holds the vector
store / embedding client directly, with a different security/ops boundary.
INTERNAL-ONLY — no auth yet (auth lands in Phase 2 of the control console).
"""

import json
from contextlib import asynccontextmanager

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from core.config import get_settings
from core.documents.store import DocumentStore
from core.persistence.db import create_engine, create_sessionmaker
from core.rag.embeddings import build_embedding_service
from core.rag.ingest import IngestService
from core.rag.vector_store import QdrantVectorStore
from core.tokens.counter import TokenCounter


class IngestRequest(BaseModel):
    text: str = Field(..., min_length=1)
    title: str | None = None
    doc_type: str = "prose"  # prose | token
    metadata: dict | None = None
    doc_id: str | None = None


class IngestResponse(BaseModel):
    doc_id: str
    chunks_ingested: int


class ToggleRequest(BaseModel):
    enabled: bool


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    embedding = build_embedding_service(settings)
    store = QdrantVectorStore(
        settings.qdrant_url, settings.qdrant_collection, settings.embedding_dim
    )
    await store.ensure_collection()
    sessionmaker = create_sessionmaker(create_engine(settings.postgres_dsn))
    documents = DocumentStore(sessionmaker)
    app.state.documents = documents
    app.state.vector_store = store
    app.state.ingest = IngestService(
        settings, embedding, store, TokenCounter(settings.tiktoken_encoding), documents
    )
    yield


app = FastAPI(title="Chatbot Admin", lifespan=lifespan)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/ingest", response_model=IngestResponse)
async def ingest(request: IngestRequest) -> IngestResponse:
    doc_id, count = await app.state.ingest.ingest_text(
        request.text, title=request.title, doc_type=request.doc_type,
        metadata=request.metadata, doc_id=request.doc_id,
    )
    return IngestResponse(doc_id=doc_id, chunks_ingested=count)


@app.post("/ingest/pptx", response_model=IngestResponse)
async def ingest_pptx(
    file: UploadFile = File(...),
    title: str | None = Form(None),
    metadata: str | None = Form(None),
    doc_id: str | None = Form(None),
) -> IngestResponse:
    data = await file.read()
    meta = json.loads(metadata) if metadata else None
    try:
        result_id, count = await app.state.ingest.ingest_pptx(
            data, title=title or file.filename, metadata=meta, doc_id=doc_id,
        )
    except Exception as exc:  # noqa: BLE001 — bad upload / parse error
        raise HTTPException(status_code=422, detail=f"could not parse pptx: {exc}")
    return IngestResponse(doc_id=result_id, chunks_ingested=count)


@app.get("/documents")
async def list_documents() -> dict:
    return {"documents": await app.state.documents.list()}


@app.get("/documents/{doc_id}/chunks")
async def document_chunks(doc_id: str) -> dict:
    doc = await app.state.documents.get(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    payloads = await app.state.vector_store.scroll_doc(doc_id)
    chunks = [
        {
            "chunk_index": p.get("chunk_index"),
            "text": p.get("text", ""),
            "title": p.get("title"),
            "metadata": p.get("metadata") or {},
            "enabled": p.get("enabled", True),
        }
        for p in payloads
    ]
    return {"document": doc, "chunks": chunks}


@app.patch("/documents/{doc_id}")
async def toggle_document(doc_id: str, request: ToggleRequest) -> dict:
    doc = await app.state.documents.set_enabled(doc_id, request.enabled)
    if doc is None:
        raise HTTPException(status_code=404, detail="document not found")
    # Mirror to Qdrant payload so retrieval can filter on `enabled`.
    await app.state.vector_store.set_payload(doc_id, {"enabled": request.enabled})
    return {"document": doc}
