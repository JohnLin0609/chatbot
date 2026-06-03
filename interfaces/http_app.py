"""HTTP gateway: a thin adapter that turns POST /chat into a stream round-trip.

Run:  uvicorn interfaces.http_app:app --port 8753
"""

import asyncio
import time
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from core.config import get_settings
from shared import redis_client as rc
from shared.events import InboundEvent, make_session_id, to_stream_fields
from interfaces.correlation import OutboundWaiter


class ChatRequest(BaseModel):
    session_id: str = Field(..., min_length=1)
    message: str = Field(..., min_length=1)


class ChatResponse(BaseModel):
    session_id: str
    reply: str


def _split_session(session_id: str) -> tuple[str, str]:
    """Derive (platform, channel_id) from a session_id like 'line:c1'."""
    if ":" in session_id:
        platform, channel_id = session_id.split(":", 1)
        return platform, channel_id
    return "http", session_id


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    redis = rc.create_redis(settings.redis_url)
    waiter = OutboundWaiter(
        redis, settings, settings.http_consumer_group, f"http-{id(app) & 0xffff}"
    )
    await waiter.start()
    app.state.settings = settings
    app.state.redis = redis
    app.state.waiter = waiter
    try:
        yield
    finally:
        await waiter.stop()
        await redis.aclose()


app = FastAPI(title="Chatbot HTTP Gateway", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"]
)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest) -> ChatResponse:
    settings = app.state.settings
    redis = app.state.redis
    waiter: OutboundWaiter = app.state.waiter

    platform, channel_id = _split_session(request.session_id)
    correlation_id = str(uuid.uuid4())
    inbound = InboundEvent(
        event_id=str(uuid.uuid4()),
        platform=platform,
        channel_id=channel_id,
        session_id=make_session_id(platform, channel_id),
        user_id="http-user",
        text=request.message,
        message_id=str(uuid.uuid4()),
        correlation_id=correlation_id,
        timestamp=time.time(),
    )

    waiter.register(correlation_id)
    await rc.publish(redis, settings.inbound_stream, to_stream_fields(inbound))

    try:
        event = await waiter.wait(correlation_id)
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Timed out waiting for reply")

    if event.status == "error":
        raise HTTPException(status_code=502, detail=f"LLM request failed: {event.error}")

    return ChatResponse(session_id=inbound.session_id, reply=event.text)
