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
    assert s.recent_turns == 4
    assert s.summary_trigger_turns == 10
    assert s.inbound_stream == "chat:inbound"
    assert s.outbound_stream == "chat:outbound"
    assert s.core_consumer_group == "core-workers"
