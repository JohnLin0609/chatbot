"""Unified console API: auth + chat + (admin-gated) document management.

Run:  uvicorn interfaces.api_app:app --port 8753

Replaces the old http_app (chat) and admin_app (ingest) — one origin + one JWT
for the Phase-3 SPA. The worker and Redis-stream transport are unchanged; the
CLI/Discord adapters stay unauthenticated (trusted server-side, publish to the
streams directly). Built via build_app(...) so tests can inject fakes.
"""

import json
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr, Field

from core.auth.deps import get_current_user, require_admin
from core.auth.security import create_access_token
from core.auth.store import DuplicateEmail, UserStore
from core.config import get_settings
from core.documents.store import DocumentStore
from core.feedback.store import FeedbackStore
from core.persistence import repository as repo
from core.settings.store import SYSTEM_PROMPT_KEY, AppSettingStore
from core.persistence.db import create_engine, create_sessionmaker
from core.rag.embeddings import build_embedding_service
from core.rag.ingest import IngestService
from core.rag.sparse import build_sparse_embedder
from core.rag.vector_store import QdrantVectorStore
from core.tokens.counter import TokenCounter
from interfaces.correlation import OutboundWaiter
from shared import redis_client as rc
from shared.events import InboundEvent, make_session_id, to_stream_fields


# --------------------------------------------------------------- schemas
class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    conversation_id: str = "default"


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    reply_message_id: int | None = None


class SystemPromptRequest(BaseModel):
    prompt: str = ""  # empty string => reset to the .env default


class FeedbackRequest(BaseModel):
    rating: int = Field(..., description="+1 (👍) or -1 (👎)")


class IngestRequest(BaseModel):
    text: str = Field(..., min_length=1)
    title: str | None = None
    doc_type: str = "prose"
    metadata: dict | None = None
    doc_id: str | None = None


class ToggleRequest(BaseModel):
    enabled: bool


def build_app(
    *,
    settings=None,
    redis=None,
    waiter=None,
    user_store=None,
    document_store=None,
    vector_store=None,
    ingest=None,
    app_settings=None,
    feedback=None,
    sessionmaker=None,
) -> FastAPI:
    settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.settings = settings
        # chat transport
        app.state.redis = redis or rc.create_redis(settings.redis_url)
        w = waiter or OutboundWaiter(
            app.state.redis, settings, settings.http_consumer_group,
            f"api-{id(app) & 0xffff}",
        )
        await w.start()
        app.state.waiter = w
        # db / rag services (injected in tests, else built from real backends)
        if user_store is not None:
            app.state.user_store = user_store
            app.state.documents = document_store
            app.state.vector_store = vector_store
            app.state.ingest = ingest
            app.state.app_settings = app_settings
            app.state.feedback = feedback
            app.state.sessionmaker = sessionmaker
        else:
            sm = create_sessionmaker(create_engine(settings.postgres_dsn))
            store = QdrantVectorStore(
                settings.qdrant_url, settings.qdrant_collection,
                settings.embedding_dim, settings.rag_sparse_vector_name,
            )
            await store.ensure_collection()
            documents = DocumentStore(sm)
            app.state.user_store = UserStore(sm)
            app.state.documents = documents
            app.state.vector_store = store
            app.state.ingest = IngestService(
                settings, build_embedding_service(settings), store,
                TokenCounter(settings.tiktoken_encoding), documents,
                build_sparse_embedder(settings),
            )
            app.state.app_settings = AppSettingStore(sm)
            app.state.feedback = FeedbackStore(sm)
            app.state.sessionmaker = sm
        try:
            yield
        finally:
            await w.stop()
            if redis is None:
                await app.state.redis.aclose()

    app = FastAPI(title="Chatbot Console API", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
    )

    @app.get("/health")
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    # ----------------------------------------------------------- auth
    @app.post("/auth/register", response_model=TokenResponse)
    async def register(req: RegisterRequest, request: Request) -> TokenResponse:
        if not settings.auth_open_registration:
            raise HTTPException(status_code=403, detail="Registration is closed")
        try:
            user = await request.app.state.user_store.create(req.email, req.password)
        except DuplicateEmail:
            raise HTTPException(status_code=409, detail="Email already registered")
        token = create_access_token(settings, sub=user["id"], role=user["role"])
        return TokenResponse(access_token=token, user=user)

    @app.post("/auth/login", response_model=TokenResponse)
    async def login(req: LoginRequest, request: Request) -> TokenResponse:
        user = await request.app.state.user_store.authenticate(req.email, req.password)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid email or password")
        token = create_access_token(settings, sub=user["id"], role=user["role"])
        return TokenResponse(access_token=token, user=user)

    @app.get("/auth/me")
    async def me(user: dict = Depends(get_current_user)) -> dict:
        return user

    # ----------------------------------------------------------- chat (auth)
    @app.post("/chat", response_model=ChatResponse)
    async def chat(
        req: ChatRequest, request: Request, user: dict = Depends(get_current_user)
    ) -> ChatResponse:
        app = request.app
        channel_id = f"{user['id']}:{req.conversation_id}"
        correlation_id = str(uuid.uuid4())
        inbound = InboundEvent(
            event_id=str(uuid.uuid4()),
            platform="web",
            channel_id=channel_id,
            session_id=make_session_id("web", channel_id),
            user_id=str(user["id"]),
            text=req.message,
            message_id=str(uuid.uuid4()),
            correlation_id=correlation_id,
            timestamp=time.time(),
        )
        app.state.waiter.register(correlation_id)
        await rc.publish(app.state.redis, settings.inbound_stream, to_stream_fields(inbound))
        try:
            event = await app.state.waiter.wait(correlation_id)
        except Exception:  # asyncio.TimeoutError
            raise HTTPException(status_code=504, detail="Timed out waiting for reply")
        if event.status == "error":
            raise HTTPException(status_code=502, detail=f"LLM request failed: {event.error}")
        return ChatResponse(
            session_id=inbound.session_id,
            reply=event.text,
            reply_message_id=event.reply_message_id,
        )

    @app.delete("/sessions/{conversation_id}", status_code=204)
    async def delete_session(
        conversation_id: str, request: Request,
        user: dict = Depends(get_current_user),
    ) -> None:
        # Ownership is structural: a user can only address keys under their own id.
        session_key = make_session_id("web", f"{user['id']}:{conversation_id}")
        async with request.app.state.sessionmaker() as db:
            await repo.delete_session_by_key(db, session_key)
            await db.commit()

    # --------------------------------------------------- feedback (any user)
    @app.post("/messages/{message_id}/feedback")
    async def rate_message(
        message_id: int, req: FeedbackRequest, request: Request,
        user: dict = Depends(get_current_user),
    ) -> dict:
        if req.rating not in (-1, 1):
            raise HTTPException(status_code=422, detail="rating must be +1 or -1")
        state = await request.app.state.feedback.rate(
            message_id, str(user["id"]), req.rating
        )
        return {"message_id": message_id, "rating": state}

    # ----------------------------------------------------- documents (admin)
    @app.post("/ingest")
    async def ingest_text(req: IngestRequest, request: Request,
                          _admin: dict = Depends(require_admin)) -> dict:
        doc_id, count = await request.app.state.ingest.ingest_text(
            req.text, title=req.title, doc_type=req.doc_type,
            metadata=req.metadata, doc_id=req.doc_id,
        )
        return {"doc_id": doc_id, "chunks_ingested": count}

    @app.post("/ingest/pptx")
    async def ingest_pptx(request: Request, file: UploadFile = File(...),
                          title: str | None = Form(None), metadata: str | None = Form(None),
                          doc_id: str | None = Form(None),
                          _admin: dict = Depends(require_admin)) -> dict:
        data = await file.read()
        meta = json.loads(metadata) if metadata else None
        try:
            result_id, count = await request.app.state.ingest.ingest_pptx(
                data, title=title or file.filename, metadata=meta, doc_id=doc_id,
            )
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(status_code=422, detail=f"could not parse pptx: {exc}")
        return {"doc_id": result_id, "chunks_ingested": count}

    @app.get("/documents")
    async def list_documents(request: Request, _admin: dict = Depends(require_admin)) -> dict:
        return {"documents": await request.app.state.documents.list()}

    @app.get("/documents/{doc_id}/chunks")
    async def document_chunks(doc_id: str, request: Request,
                              _admin: dict = Depends(require_admin)) -> dict:
        doc = await request.app.state.documents.get(doc_id)
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found")
        payloads = await request.app.state.vector_store.scroll_doc(doc_id)
        chunks = [
            {"chunk_index": p.get("chunk_index"), "text": p.get("text", ""),
             "title": p.get("title"), "metadata": p.get("metadata") or {},
             "enabled": p.get("enabled", True)}
            for p in payloads
        ]
        return {"document": doc, "chunks": chunks}

    @app.patch("/documents/{doc_id}")
    async def toggle_document(doc_id: str, req: ToggleRequest, request: Request,
                              _admin: dict = Depends(require_admin)) -> dict:
        doc = await request.app.state.documents.set_enabled(doc_id, req.enabled)
        if doc is None:
            raise HTTPException(status_code=404, detail="document not found")
        await request.app.state.vector_store.set_payload(doc_id, {"enabled": req.enabled})
        return {"document": doc}

    # ----------------------------------------------- system prompt (admin)
    @app.get("/admin/system-prompt")
    async def get_system_prompt(request: Request,
                                _admin: dict = Depends(require_admin)) -> dict:
        override = await request.app.state.app_settings.get(SYSTEM_PROMPT_KEY)
        return {
            "prompt": override if override is not None else settings.system_prompt,
            "is_default": override is None,
            "default": settings.system_prompt,
        }

    @app.put("/admin/system-prompt")
    async def set_system_prompt(req: SystemPromptRequest, request: Request,
                                _admin: dict = Depends(require_admin)) -> dict:
        prompt = req.prompt.strip()
        if prompt:
            await request.app.state.app_settings.set(SYSTEM_PROMPT_KEY, prompt)
            return {"prompt": prompt, "is_default": False, "default": settings.system_prompt}
        # empty => clear the override, fall back to the .env default
        await request.app.state.app_settings.delete(SYSTEM_PROMPT_KEY)
        return {"prompt": settings.system_prompt, "is_default": True,
                "default": settings.system_prompt}

    # ----------------------------------------------- feedback summary (admin)
    @app.get("/admin/feedback/summary")
    async def feedback_summary(request: Request,
                               _admin: dict = Depends(require_admin)) -> dict:
        return await request.app.state.feedback.summary()

    return app


app = build_app()
