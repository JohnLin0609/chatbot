"""Shared test fixtures: settings, fakeredis, in-memory sqlite, fake LLM."""

import fakeredis.aioredis
import pytest_asyncio

from core.config import Provider, Settings
from core.persistence.db import create_engine, create_sessionmaker
from core.persistence.models import Base


def make_settings(**kwargs) -> Settings:
    base = dict(
        _env_file=None,
        provider=Provider.openai,
        openai_api_key="x",
        recent_turns=2,
        summary_trigger_turns=3,
    )
    base.update(kwargs)
    return Settings(**base)


class FakeChat:
    """Deterministic stand-in for a ChatService."""

    def __init__(self, reply: str | None = None) -> None:
        self._reply = reply
        self.calls: list[list[dict]] = []

    async def generate_reply(self, session_id: str, messages: list[dict]) -> str:
        self.calls.append(messages)
        if self._reply is not None:
            return self._reply
        last_user = [m for m in messages if m["role"] == "user"][-1]["content"]
        return f"reply-to:{last_user}"


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
    engine = create_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield create_sessionmaker(engine)
    await engine.dispose()
