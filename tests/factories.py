"""Plain factory functions shared by the pytest fixtures (tests/conftest.py)
and the BDD World (tests/bdd/world.py).

The BDD layer drives async code from sync pytest-bdd steps via its own
asyncio.Runner, so it cannot consume pytest-asyncio fixtures — both layers
build their resources through these factories instead.
"""

import fakeredis.aioredis
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine
from sqlalchemy.pool import StaticPool

from core.config import Settings
from core.facts.extractor import FactExtractor
from core.facts.store import UserMemoryStore
from core.memory.hot_store import HotStore
from core.persistence.db import create_sessionmaker
from core.persistence.models import Base
from core.pipeline import PipelineDeps
from core.summary.summarizer import Summarizer
from core.tokens.counter import TokenCounter
from core.tools.loop import ToolRunner
from core.tools.registry import ToolRegistry


def new_fake_redis():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


async def new_sqlite_engine() -> AsyncEngine:
    # StaticPool keeps a single shared connection so every session (including
    # background-task sessions) sees the same in-memory database.
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    return engine


def build_deps(settings: Settings, redis, sessionmaker, chat,
               registry: ToolRegistry | None = None, **overrides) -> PipelineDeps:
    """Full pipeline deps over fakes. `overrides` sets any PipelineDeps field
    (classifier/retriever/reranker/vector_store/eval_logger/...)."""
    from tests.conftest import FakeEmbedding, FakeVectorStore

    counter = TokenCounter(settings.tiktoken_encoding)
    kwargs = dict(
        settings=settings,
        hot_store=HotStore(redis, settings),
        sessionmaker=sessionmaker,
        chat_service=chat,
        summarizer=Summarizer(settings, chat),
        token_counter=counter,
        user_memory_store=UserMemoryStore(redis, settings),
        fact_extractor=FactExtractor(settings, chat, counter),
        tool_runner=ToolRunner(chat, registry or ToolRegistry(), settings),
        embedding_service=FakeEmbedding(),
        vector_store=FakeVectorStore(),
    )
    kwargs.update(overrides)
    return PipelineDeps(**kwargs)
