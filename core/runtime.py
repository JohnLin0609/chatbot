"""Wire concrete dependencies (Redis, Postgres, LLM, RAG) into PipelineDeps."""

from redis.asyncio import Redis

from core.config import Settings
from core.facts.extractor import FactExtractor
from core.facts.store import UserMemoryStore
from core.llm.factory import build_chat_service
from core.memory.hot_store import HotStore
from core.persistence.db import create_engine, create_sessionmaker
from core.pipeline import PipelineDeps
from core.rag.embeddings import build_embedding_service
from core.rag.vector_store import QdrantVectorStore
from core.summary.summarizer import Summarizer
from core.tokens.counter import TokenCounter
from core.tools.loop import ToolRunner
from core.tools.registry import ToolRegistry, register_default_tools
from core.web.brave import build_web_search_service


def build_pipeline_deps(settings: Settings, redis: Redis) -> PipelineDeps:
    engine = create_engine(settings.postgres_dsn)
    sessionmaker = create_sessionmaker(engine)
    chat_service = build_chat_service(settings)
    hot_store = HotStore(redis, settings)
    summarizer = Summarizer(settings, chat_service)
    counter = TokenCounter(settings.tiktoken_encoding)
    user_memory_store = UserMemoryStore(redis, settings)
    fact_extractor = FactExtractor(settings, chat_service, counter)

    embedding_service = build_embedding_service(settings)
    vector_store = QdrantVectorStore(
        settings.qdrant_url, settings.qdrant_collection, settings.embedding_dim
    )
    web_search_service = build_web_search_service(settings)
    registry = ToolRegistry()
    register_default_tools(registry, settings)
    tool_runner = ToolRunner(chat_service, registry, settings)

    return PipelineDeps(
        settings=settings,
        hot_store=hot_store,
        sessionmaker=sessionmaker,
        chat_service=chat_service,
        summarizer=summarizer,
        token_counter=counter,
        user_memory_store=user_memory_store,
        fact_extractor=fact_extractor,
        tool_runner=tool_runner,
        embedding_service=embedding_service,
        vector_store=vector_store,
        web_search_service=web_search_service,
    )
