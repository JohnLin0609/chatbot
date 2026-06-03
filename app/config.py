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


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

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

    @property
    def model_name(self) -> str:
        """Resolved model: explicit MODEL, else the provider default."""
        return self.model or DEFAULT_MODELS[self.provider]


@lru_cache
def get_settings() -> Settings:
    """Cached settings instance for dependency injection."""
    return Settings()
