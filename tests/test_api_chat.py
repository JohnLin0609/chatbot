"""/chat auth gating + identity flow (stream round-trip stubbed)."""

import json

import fakeredis.aioredis
import httpx
import pytest_asyncio
from httpx import ASGITransport

from core.auth.deps import get_current_user
from interfaces.api_app import build_app
from shared.events import OutboundEvent
from tests.conftest import make_settings

S = make_settings(jwt_secret="api-secret")


class FakeWaiter:
    def __init__(self, *a, **k):
        pass

    async def start(self):
        pass

    async def stop(self):
        pass

    def register(self, cid):
        return None

    async def wait(self, cid):
        return OutboundEvent(
            event_id="o1", in_reply_to="e1", platform="web", channel_id="7:default",
            session_id="web:7:default", correlation_id=cid, text="pong",
            status="ok", timestamp=0.0,
        )


def _user():
    return {"id": 7, "email": "u@x.com", "role": "user"}


async def _make_app():
    app = build_app(settings=S)
    app.state.settings = S
    app.state.redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.state.waiter = FakeWaiter()
    return app


@pytest_asyncio.fixture
async def app():
    return await _make_app()


async def _client(app):
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_chat_requires_auth(app):
    async with await _client(app) as c:
        r = await c.post("/chat", json={"message": "hi"})
    assert r.status_code == 401


async def test_chat_authed_flows_user_identity(app):
    app.dependency_overrides[get_current_user] = _user
    async with await _client(app) as c:
        r = await c.post("/chat", json={"message": "hello", "conversation_id": "t1"},
                         headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json()["reply"] == "pong"

    # the published inbound carries the authenticated user's identity
    entries = await app.state.redis.xrange(S.inbound_stream)
    assert entries, "no inbound published"
    data = json.loads(entries[-1][1]["data"])
    assert data["user_id"] == "7"
    assert data["platform"] == "web"
    assert data["channel_id"] == "7:t1"
