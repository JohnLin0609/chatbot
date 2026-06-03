"""Application settings loaded from environment / .env file."""

from enum import Enum
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Provider(str, Enum):
    anthropic = "anthropic"
    openai = "openai"
    gemini = "gemini"
    ollama = "ollama"


# Default model per provider, used when MODEL is left unset.
DEFAULT_MODELS: dict[Provider, str] = {
    Provider.anthropic: "claude-sonnet-4-6",
    Provider.openai: "gpt-4o-mini",
    Provider.gemini: "gemini-2.0-flash",
    Provider.ollama: "llama3.2",
}


DEFAULT_CHANNEL_SUMMARY_PROMPT = (
    "You are a conversation summariser. Merge the existing summary with the new "
    "turns into a SINGLE very concise running summary of at most 150 tokens. "
    "Preserve facts, decisions, open questions, and preferences. Third-person "
    "bullet points. Do not invent anything not in the conversation."
)

DEFAULT_FACT_PROMPT = (
    "You maintain a durable per-user memory document. Given the user's current "
    "memory and recent messages, decide what to update. Respond ONLY with JSON:\n"
    '{"rolling_summary": "<=400-token third-person summary of this user across '
    'sessions", "facts": [{"key": "snake_case", "value": "...", "cardinality": '
    '"single|multi", "confidence": 0.0-1.0}], "retire": [{"key": "...", "reason": '
    '"..."}]}\n'
    "Use cardinality 'single' for facts with one value (new value replaces old), "
    "'multi' for list-like facts (values accumulate). Only include facts that are "
    "clearly stated or strongly implied. Do not invent. Omit unchanged facts.\n"
    "When a fact's value CHANGES, put it in 'facts' with the new value (the old "
    "value is archived automatically) — do NOT also retire it. Use 'retire' ONLY "
    "for a fact that is no longer true AND has no replacement value. Never list "
    "the same key in both 'facts' and 'retire'."
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # ------------------------------------------------------------------ LLM
    # Which LLM backend to talk to.
    provider: Provider = Provider.anthropic

    # Model name. If left empty, a per-provider default is applied (see `model_name`).
    model: str = ""

    # API keys — only the one for the selected provider is required.
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""

    # Ollama runs locally and needs no key, just a host.
    ollama_host: str = "http://localhost:11434"

    # Shared generation settings.
    system_prompt: str = (
        "You are a friendly, concise assistant. "
        "Answer in the same language the user writes in."
    )
    max_tokens: int = 1024

    # ---------------------------------------------------------------- Redis
    # Defaults match docker-compose's dedicated host ports (6380/5433) so the
    # app talks to this project's own Redis/Postgres, not whatever else may be
    # running on the conventional 6379/5432.
    redis_url: str = "redis://localhost:6380/0"
    redis_key_prefix: str = "chat"
    inbound_stream: str = "chat:inbound"
    outbound_stream: str = "chat:outbound"
    core_consumer_group: str = "core-workers"
    http_consumer_group: str = "http-gateway"
    cli_consumer_group: str = "cli-gateway"

    # ------------------------------------------------------------- Postgres
    postgres_dsn: str = "postgresql+asyncpg://chat:chat@localhost:5434/chat"

    # ------------------------------------------------------- Tokenisation
    tiktoken_encoding: str = "o200k_base"

    # ------------------------------------------------------ Memory/context
    hot_ttl_seconds: int = 604800  # 7 days
    # Tier-1: current-context window size (whole turns kept under this budget).
    context_window_tokens: int = 3000

    # ----------------------------------------------- Tier-2 channel summary
    # Turns overflowing the window are folded into a short per-channel summary.
    channel_summary_token_cap: int = 150
    channel_summary_system_prompt: str = DEFAULT_CHANNEL_SUMMARY_PROMPT

    # ------------------------------------------ Tier-3 per-user fact memory
    # Trigger fact extraction once a user's un-extracted messages reach this.
    fact_extraction_tokens: int = 6000
    fact_extraction_async: bool = False
    fact_system_prompt: str = DEFAULT_FACT_PROMPT
    # Caps on the RENDERED (slimmed) memory injected into the prompt.
    personal_memory_token_cap: int = 800
    rolling_summary_token_cap: int = 400
    # Ranking weights for which facts to inject when over the cap.
    fact_confidence_weight: float = 1.0
    fact_recency_weight: float = 1.0
    fact_recency_halflife_days: float = 30.0

    # ------------------------------------------------------------- Gateway
    reply_timeout_seconds: float = 30.0  # how long /chat and the CLI wait for a reply

    # ----------------------------------------------- Tier-4 RAG / vector store
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "knowledge"

    # Embedding model — fixed for the whole collection, independent of `provider`.
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    embedding_batch_size: int = 64

    # RAG retrieval (used by the search_knowledge tool).
    rag_top_k: int = 5
    rag_score_threshold: float = 0.0  # 0 = no threshold; tune after observing scores

    # Curated-document ingestion chunking.
    ingest_chunk_tokens: int = 512
    ingest_chunk_overlap: int = 64

    # ------------------------------------------------------------- Tools
    enable_tools: bool = True
    tool_max_iterations: int = 4

    @property
    def model_name(self) -> str:
        """Resolved model: explicit MODEL, else the provider default."""
        return self.model or DEFAULT_MODELS[self.provider]


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance for dependency injection."""
    return Settings()
