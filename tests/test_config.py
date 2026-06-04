"""Settings / provider-resolution tests."""

from core.config import DEFAULT_MODELS, Provider, Settings


def _settings(**kwargs) -> Settings:
    # _env_file=None keeps tests independent of any local .env file.
    return Settings(_env_file=None, **kwargs)


def test_default_provider_is_anthropic():
    assert _settings().provider is Provider.anthropic


def test_provider_parsed_from_string():
    assert _settings(provider="openai").provider is Provider.openai


def test_model_name_falls_back_to_provider_default():
    for provider, default in DEFAULT_MODELS.items():
        assert _settings(provider=provider).model_name == default


def test_explicit_model_overrides_default():
    s = _settings(provider="openai", model="gpt-5.4-mini")
    assert s.model_name == "gpt-5.4-mini"


def test_new_infra_defaults():
    s = _settings()
    assert s.context_window_tokens == 3000
    assert s.fact_extraction_tokens == 6000
    assert s.personal_memory_token_cap == 800
    assert s.channel_summary_token_cap == 150
    assert s.tiktoken_encoding == "o200k_base"
    assert s.inbound_stream == "chat:inbound"
    assert s.core_consumer_group == "core-workers"


def test_session_ttl_and_finalize_defaults():
    s = _settings()
    assert s.hot_ttl_seconds == 600  # 10 min session cache
    assert s.user_memory_ttl_seconds == 604800  # decoupled tier-3 mirror
    assert s.session_finalize_enabled is True
    assert s.session_finalize_idle_seconds == 600
    assert s.session_sweep_interval_seconds == 60
