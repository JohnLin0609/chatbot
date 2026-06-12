"""Production hardening: APP_ENV enforcement, rate limiting, health checks,
LLM timeout/retry wrapper."""

import asyncio

import httpx
import pytest
from httpx import ASGITransport

from core.auth.store import UserStore
from core.config import Settings
from core.llm.base import ChatService, ChatServiceError
from core.llm.resilience import ResilientChatService
from core.ratelimit import RateLimiter
from interfaces.api_app import build_app
from tests.conftest import make_settings


# --------------------------------------------------- production settings
def test_production_requires_jwt_secret():
    with pytest.raises(ValueError, match="JWT_SECRET"):
        make_settings(app_env="production", cors_allow_origins="https://x.com")


def test_production_rejects_wildcard_cors():
    with pytest.raises(ValueError, match="CORS_ALLOW_ORIGINS"):
        make_settings(app_env="production", jwt_secret="s" * 32)


def test_production_closes_registration_by_default():
    s = make_settings(app_env="production", jwt_secret="s" * 32,
                      cors_allow_origins="https://x.com")
    assert s.auth_open_registration is False


def test_production_registration_stays_open_when_explicit():
    s = make_settings(app_env="production", jwt_secret="s" * 32,
                      cors_allow_origins="https://x.com",
                      auth_open_registration=True)
    assert s.auth_open_registration is True


def test_dev_defaults_unchanged():
    s = make_settings()
    assert not s.is_production
    assert s.auth_open_registration is True
    assert s.cors_origins == ["*"]


def test_cors_origins_csv_parsing():
    s = make_settings(cors_allow_origins="https://a.com, https://b.com")
    assert s.cors_origins == ["https://a.com", "https://b.com"]


# --------------------------------------------------------- rate limiter
async def test_rate_limiter_blocks_over_limit(redis):
    rl = RateLimiter(redis, "t:rl")
    assert await rl.hit("b", limit=2) is True
    assert await rl.hit("b", limit=2) is True
    assert await rl.hit("b", limit=2) is False


async def test_rate_limiter_buckets_are_independent(redis):
    rl = RateLimiter(redis, "t:rl")
    assert await rl.hit("a", limit=1) is True
    assert await rl.hit("b", limit=1) is True


async def test_rate_limiter_fails_open_without_redis():
    class Broken:
        async def incr(self, key):
            raise ConnectionError("down")

    assert await RateLimiter(Broken(), "t:rl").hit("b", limit=1) is True


async def test_login_rate_limited_429(sessionmaker, redis):
    s = make_settings(jwt_secret="api-secret", rate_limit_auth_per_minute=2)
    app = build_app(settings=s)
    app.state.settings = s
    app.state.user_store = UserStore(sessionmaker)
    app.state.limiter = RateLimiter(redis, "t:rl")
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        await c.post("/auth/register", json={"email": "a@x.com", "password": "password1"})
        creds = {"email": "a@x.com", "password": "password1"}
        assert (await c.post("/auth/login", json=creds)).status_code == 200
        # register + login consumed the 2-hit budget for this client IP
        assert (await c.post("/auth/login", json=creds)).status_code == 429


async def test_chat_rate_limited_429(sessionmaker, redis):
    s = make_settings(jwt_secret="api-secret", rate_limit_chat_per_minute=0)
    app = build_app(settings=s)
    app.state.settings = s
    app.state.user_store = UserStore(sessionmaker)
    app.state.limiter = RateLimiter(redis, "t:rl")
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/auth/register", json={"email": "a@x.com", "password": "password1"})
        token = r.json()["access_token"]
        r = await c.post("/chat", json={"message": "hi"},
                         headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 429


async def test_rate_limit_disabled_passes(sessionmaker, redis):
    s = make_settings(jwt_secret="api-secret", rate_limit_enabled=False,
                      rate_limit_auth_per_minute=0)
    app = build_app(settings=s)
    app.state.settings = s
    app.state.user_store = UserStore(sessionmaker)
    app.state.limiter = RateLimiter(redis, "t:rl")
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.post("/auth/register", json={"email": "a@x.com", "password": "password1"})
        assert r.status_code == 200


# --------------------------------------------------------- health check
async def test_health_checks_dependencies(sessionmaker, redis):
    s = make_settings(jwt_secret="api-secret")
    app = build_app(settings=s)
    app.state.redis = redis
    app.state.sessionmaker = sessionmaker
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "redis": "ok", "postgres": "ok"}


async def test_health_503_when_redis_down(sessionmaker):
    class Broken:
        async def ping(self):
            raise ConnectionError("down")

    s = make_settings(jwt_secret="api-secret")
    app = build_app(settings=s)
    app.state.redis = Broken()
    app.state.sessionmaker = sessionmaker
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        r = await c.get("/health")
    assert r.status_code == 503
    assert "redis" in r.json()["detail"]


# ------------------------------------------------- resilient chat service
class FlakyChat(ChatService):
    """Fails `failures` times, then succeeds."""

    def __init__(self, settings, failures: int, exc: Exception | None = None,
                 hang: bool = False) -> None:
        super().__init__(settings)
        self.calls = 0
        self._failures = failures
        self._exc = exc or ChatServiceError("transient")
        self._hang = hang

    async def generate_reply(self, session_id, messages):
        self.calls += 1
        if self.calls <= self._failures:
            if self._hang:
                await asyncio.sleep(60)
            raise self._exc
        return "ok"


def _resilience_settings(**kwargs) -> Settings:
    return make_settings(llm_max_retries=2, llm_retry_backoff_seconds=0.001,
                         llm_timeout_seconds=0.05, **kwargs)


async def test_resilient_retries_then_succeeds():
    s = _resilience_settings()
    inner = FlakyChat(s, failures=2)
    svc = ResilientChatService(inner, s)
    assert await svc.generate_reply("s", [{"role": "user", "content": "x"}]) == "ok"
    assert inner.calls == 3


async def test_resilient_exhausted_raises_chat_error():
    s = _resilience_settings()
    inner = FlakyChat(s, failures=99)
    svc = ResilientChatService(inner, s)
    with pytest.raises(ChatServiceError):
        await svc.generate_reply("s", [])
    assert inner.calls == 3  # 1 + 2 retries


async def test_resilient_timeout_becomes_chat_error():
    s = _resilience_settings()
    inner = FlakyChat(s, failures=99, hang=True)
    svc = ResilientChatService(inner, s)
    with pytest.raises(ChatServiceError, match="timed out"):
        await svc.generate_reply("s", [])


async def test_resilient_passes_through_supports_tools():
    s = _resilience_settings()
    assert ResilientChatService(FlakyChat(s, 0), s).supports_tools is False
