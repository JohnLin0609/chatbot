"""HTTP gateway tests with the stream round-trip stubbed (no redis/worker).

The OutboundWaiter and Redis client are replaced so /chat can be exercised
without a running core worker.
"""

import asyncio

import fakeredis.aioredis
import pytest
from fastapi.testclient import TestClient

import interfaces.http_app as http_app
from shared.events import OutboundEvent


class FakeWaiter:
    mode = "ok"  # "ok" | "error" | "timeout"

    def __init__(self, *args, **kwargs):
        pass

    async def start(self):
        pass

    async def stop(self):
        pass

    def register(self, correlation_id):
        return None

    async def wait(self, correlation_id):
        if FakeWaiter.mode == "timeout":
            raise asyncio.TimeoutError
        status = "error" if FakeWaiter.mode == "error" else "ok"
        return OutboundEvent(
            event_id="o1", in_reply_to="e1", platform="http", channel_id="c1",
            session_id="http:c1", correlation_id=correlation_id,
            text="pong" if status == "ok" else "",
            status=status, error="boom" if status == "error" else None,
            timestamp=0.0,
        )


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(http_app, "OutboundWaiter", FakeWaiter)
    monkeypatch.setattr(
        http_app.rc, "create_redis",
        lambda url: fakeredis.aioredis.FakeRedis(decode_responses=True),
    )
    FakeWaiter.mode = "ok"
    with TestClient(http_app.app) as c:
        yield c


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_chat_success(client):
    r = client.post("/chat", json={"session_id": "line:c1", "message": "hi"})
    assert r.status_code == 200
    assert r.json() == {"session_id": "line:c1", "reply": "pong"}


def test_chat_error_returns_502(client):
    FakeWaiter.mode = "error"
    r = client.post("/chat", json={"session_id": "line:c1", "message": "hi"})
    assert r.status_code == 502


def test_chat_timeout_returns_504(client):
    FakeWaiter.mode = "timeout"
    r = client.post("/chat", json={"session_id": "line:c1", "message": "hi"})
    assert r.status_code == 504


@pytest.mark.parametrize(
    "payload",
    [
        {"session_id": "line:c1", "message": ""},
        {"session_id": "line:c1"},
        {"message": "hi"},
    ],
)
def test_chat_validation_errors(client, payload):
    r = client.post("/chat", json=payload)
    assert r.status_code == 422
