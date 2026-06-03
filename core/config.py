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


DEFAULT_SUMMARY_PROMPT = (
    "You are a conversation summariser. Merge the existing summary with the new "
    "turns into a single concise running summary. Preserve facts, decisions, open "
    "questions, and user preferences. Use third-person bullet points. Do not invent "
    "anything that was not in the conversation."
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
    redis_url: str = "redis://localhost:6379/0"
    redis_key_prefix: str = "chat"
    inbound_stream: str = "chat:inbound"
    outbound_stream: str = "chat:outbound"
    core_consumer_group: str = "core-workers"
    http_consumer_group: str = "http-gateway"
    cli_consumer_group: str = "cli-gateway"

    # ------------------------------------------------------------- Postgres
    postgres_dsn: str = "postgresql+asyncpg://chat:chat@localhost:5432/chat"

    # -------------------------------------------------------- Memory/context
    recent_turns: int = 4  # how many recent turns to keep hot / feed the LLM
    hot_ttl_seconds: int = 604800  # 7 days

    # ------------------------------------------------------------- Summary
    summary_trigger_turns: int = 10
    summary_trigger_tokens: int = 2000  # 0 disables the token threshold
    summary_async: bool = False
    summary_system_prompt: str = DEFAULT_SUMMARY_PROMPT

    # ------------------------------------------------------------- Gateway
    reply_timeout_seconds: float = 30.0  # how long /chat and the CLI wait for a reply

    @property
    def model_name(self) -> str:
        """Resolved model: explicit MODEL, else the provider default."""
        return self.model or DEFAULT_MODELS[self.provider]


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance for dependency injection."""
    return Settings()
