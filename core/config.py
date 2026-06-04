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
    discord_consumer_group: str = "discord-gateway"
    # Ephemeral progress (pub/sub): the worker broadcasts thinking/tool status so
    # adapters can show live indicators (e.g. Discord reactions).
    progress_channel: str = "chat:progress"

    # ------------------------------------------------------------- Postgres
    postgres_dsn: str = "postgresql+asyncpg://chat:chat@localhost:5434/chat"

    # ------------------------------------------------------- Tokenisation
    tiktoken_encoding: str = "o200k_base"

    # ------------------------------------------------------ Memory/context
    # Session conversation cache (recent turns + channel summary). 10 min idle =
    # the user has left; the sweeper then finalises the session (see below).
    hot_ttl_seconds: int = 600
    # Tier-3 per-user memory mirror — decoupled from the session cache so the
    # short session TTL doesn't thrash per-user memory caching. Postgres remains
    # authoritative either way.
    user_memory_ttl_seconds: int = 604800  # 7 days
    # Tier-1: current-context window size (whole turns kept under this budget).
    context_window_tokens: int = 3000

    # ------------------------------------------- Session finalization (sweeper)
    # When a session's hot cache has expired (idle past the threshold), a worker
    # sweeper folds the conversation into durable memory: tier-2 channel summary
    # + tier-3 per-user fact extraction (forced, bypassing the token threshold).
    session_finalize_enabled: bool = True
    session_finalize_idle_seconds: int = 600
    session_sweep_interval_seconds: int = 60
    session_sweep_batch: int = 50

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

    # ------------------------------------------------------------- Auth (API)
    # JWT signing secret — set in prod; if empty an ephemeral dev secret is used
    # (tokens won't survive a restart). Access-token only.
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    jwt_expiry_minutes: int = 1440  # 24h
    # Open self-registration; the first account created becomes admin.
    auth_open_registration: bool = True

    # ----------------------------------------------- Tier-4 RAG / vector store
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "knowledge"

    # Embedding model — fixed for the whole collection, independent of `provider`.
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dim: int = 1536
    embedding_batch_size: int = 64

    # RAG retrieval.
    rag_top_k: int = 5
    rag_score_threshold: float = 0.0  # 0 = no threshold; tune after observing scores

    # Curated-document ingestion chunking.
    ingest_chunk_tokens: int = 512
    ingest_chunk_overlap: int = 64
    # Per-type chunking (Phase 1): default strategy + spaCy sentence-grouping params.
    default_chunk_strategy: str = "prose"  # prose | slides | token
    spacy_model: str = "xx_sent_ud_sm"  # multilingual sentence segmentation
    chunk_sentence_overlap: int = 1  # sentences carried between prose chunks

    # Hybrid (dense + BM25 sparse) retrieval.
    rag_sparse_enabled: bool = True
    rag_sparse_vector_name: str = "text-sparse"
    rag_prefetch_limit: int = 50  # candidates per branch before RRF fusion
    rag_fusion: str = "rrf"

    # Adaptive-RAG routing (front LLM classifier).
    adaptive_classifier_enabled: bool = True
    adaptive_classifier_model: str = ""  # "" = main chat model
    rag_medium_top_k: int = 3
    rag_complex_candidates: int = 20  # fused top-N fed to the reranker
    rag_complex_top_k: int = 3

    # Rerank (complex tier only) — local Qwen3-Reranker.
    rag_reranker_enabled: bool = True
    rag_reranker_model: str = "Qwen/Qwen3-Reranker-0.6B"
    rag_reranker_device: str = "auto"

    # ------------------------------------------------------------- Tools
    enable_tools: bool = True
    tool_max_iterations: int = 4

    # ------------------------------------------------- Web search (Brave API)
    # The web_search tool is registered ONLY when an API key is present.
    brave_api_key: str = ""
    brave_search_url: str = "https://api.search.brave.com/res/v1/web/search"
    brave_search_count: int = 5  # default result count when the model omits it
    brave_search_country: str = ""  # optional ISO country (e.g. "us"); "" = Brave default
    brave_search_lang: str = ""  # optional UI/search language (e.g. "en"); "" = Brave default
    brave_search_timeout: float = 8.0

    # ------------------------------------------------------------- Discord
    discord_bot_token: str = ""
    # Optional noise guard: CSV of guild IDs the bot will answer in ("" = all).
    discord_allowed_guilds: str = ""

    @property
    def model_name(self) -> str:
        """Resolved model: explicit MODEL, else the provider default."""
        return self.model or DEFAULT_MODELS[self.provider]


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance for dependency injection."""
    return Settings()
