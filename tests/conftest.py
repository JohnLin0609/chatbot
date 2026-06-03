"""Shared test fixtures: settings, fakeredis, in-memory sqlite, fake LLM."""

import fakeredis.aioredis
import pytest_asyncio
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import Provider, Settings
from core.persistence.db import create_sessionmaker
from core.persistence.models import Base


def make_settings(**kwargs) -> Settings:
    base = dict(
        _env_file=None,
        provider=Provider.openai,
        openai_api_key="x",
        # Small windows so tests trigger overflow/extraction quickly.
        context_window_tokens=40,
        fact_extraction_tokens=60,
    )
    base.update(kwargs)
    return Settings(**base)


class FakeChat:
    """Deterministic stand-in for a ChatService.

    supports_tools=False so ToolRunner takes the fallback single-completion
    path — keeping existing pipeline assertions (reply-to:...) unchanged.
    """

    supports_tools = False

    def __init__(self, reply: str | None = None) -> None:
        self._reply = reply
        self.calls: list[list[dict]] = []

    async def generate_reply(self, session_id: str, messages: list[dict]) -> str:
        self.calls.append(messages)
        if self._reply is not None:
            return self._reply
        last_user = [m for m in messages if m["role"] == "user"][-1]["content"]
        return f"reply-to:{last_user}"

    async def complete(self, session_id, messages, tools=None):
        from core.tools.schemas import ChatCompletionResult

        text = await self.generate_reply(session_id, messages)
        return ChatCompletionResult(
            text=text, tool_calls=[],
            raw_assistant_message={"role": "assistant", "content": text},
        )


class FakeEmbedding:
    dim = 1536

    async def embed(self, texts):
        return [[0.1, 0.2, 0.3] for _ in texts]


class FakeVectorStore:
    """No-op vector store for pipeline tests (RAG path not exercised)."""

    def __init__(self, hits=None):
        self._hits = hits or []

    async def ensure_collection(self):
        pass

    async def search(self, vector, top_k, *, source=None, score_threshold=None):
        return self._hits

    async def upsert(self, points):
        pass

    async def delete_doc(self, doc_id):
        pass


@pytest_asyncio.fixture
async def settings() -> Settings:
    return make_settings()


@pytest_asyncio.fixture
async def redis():
    client = fakeredis.aioredis.FakeRedis(decode_responses=True)
    yield client
    await client.aclose()


@pytest_asyncio.fixture
async def sessionmaker():
    # StaticPool keeps a single shared connection so every session (including
    # background-task sessions) sees the same in-memory database.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield create_sessionmaker(engine)
    await engine.dispose()
