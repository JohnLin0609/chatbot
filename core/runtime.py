"""Wire concrete dependencies (Redis, Postgres, LLM) into PipelineDeps."""

from redis.asyncio import Redis

from core.config import Settings
from core.llm.factory import build_chat_service
from core.memory.hot_store import HotStore
from core.persistence.db import create_engine, create_sessionmaker
from core.pipeline import PipelineDeps
from core.summary.summarizer import Summarizer


def build_pipeline_deps(settings: Settings, redis: Redis) -> PipelineDeps:
    engine = create_engine(settings.postgres_dsn)
    sessionmaker = create_sessionmaker(engine)
    chat_service = build_chat_service(settings)
    hot_store = HotStore(redis, settings)
    summarizer = Summarizer(settings, chat_service, hot_store)
    return PipelineDeps(
        settings=settings,
        hot_store=hot_store,
        sessionmaker=sessionmaker,
        chat_service=chat_service,
        summarizer=summarizer,
    )
