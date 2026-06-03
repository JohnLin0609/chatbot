"""FastAPI application for the simple chatbot backend."""

from functools import lru_cache

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

from app.chat_service import ChatService, ChatServiceError, build_chat_service
from app.config import get_settings
from app.schemas import ChatRequest, ChatResponse

app = FastAPI(title="Simple Chatbot Backend")

# Allow local frontends to call the API during development.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@lru_cache
def get_chat_service() -> ChatService:
    """Cached ChatService so the provider client is created once."""
    return build_chat_service(get_settings())


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/chat", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    try:
        reply = await service.generate_reply(request.session_id, request.message)
    except ChatServiceError as exc:
        raise HTTPException(status_code=502, detail=f"LLM request failed: {exc}")

    return ChatResponse(session_id=request.session_id, reply=reply)
