"""HTTP-level tests for the FastAPI app, with the ChatService mocked out."""

import pytest
from fastapi.testclient import TestClient

from app.chat_service import ChatService, ChatServiceError
from app.main import app, get_chat_service


class _EchoService(ChatService):
    def __init__(self):  # no settings / no real client needed
        pass

    async def generate_reply(self, session_id: str, message: str) -> str:
        return f"echo:{message}"


class _FailingService(ChatService):
    def __init__(self):
        pass

    async def generate_reply(self, session_id: str, message: str) -> str:
        raise ChatServiceError("upstream down")


@pytest.fixture
def client():
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_chat_success_echoes_and_preserves_session(client):
    app.dependency_overrides[get_chat_service] = lambda: _EchoService()
    r = client.post("/chat", json={"session_id": "s1", "message": "hi"})
    assert r.status_code == 200
    assert r.json() == {"session_id": "s1", "reply": "echo:hi"}


def test_chat_upstream_failure_returns_502(client):
    app.dependency_overrides[get_chat_service] = lambda: _FailingService()
    r = client.post("/chat", json={"session_id": "s1", "message": "hi"})
    assert r.status_code == 502


@pytest.mark.parametrize(
    "payload",
    [
        {"session_id": "s1", "message": ""},  # empty message
        {"session_id": "s1"},                 # missing message
        {"message": "hi"},                    # missing session_id
    ],
)
def test_chat_validation_errors(client, payload):
    app.dependency_overrides[get_chat_service] = lambda: _EchoService()
    r = client.post("/chat", json=payload)
    assert r.status_code == 422
