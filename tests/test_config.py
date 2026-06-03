"""Settings / provider-resolution tests."""

from app.config import DEFAULT_MODELS, Provider, Settings


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
