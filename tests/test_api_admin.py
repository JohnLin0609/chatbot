"""Admin-gated document routes: 403 for users, 200 for admins."""

import httpx
import pytest_asyncio
from httpx import ASGITransport

from core.auth.deps import get_current_user
from interfaces.api_app import build_app
from tests.conftest import make_settings

S = make_settings(jwt_secret="api-secret")


class FakeDocStore:
    def __init__(self):
        self.toggled = None

    async def list(self):
        return [{"doc_id": "d1", "title": "Doc", "doc_type": "prose",
                 "enabled": True, "chunk_count": 2}]

    async def get(self, doc_id):
        return {"doc_id": doc_id, "enabled": True} if doc_id == "d1" else None

    async def set_enabled(self, doc_id, enabled):
        if doc_id != "d1":
            return None
        self.toggled = enabled
        return {"doc_id": doc_id, "enabled": enabled}


class FakeVectorStore:
    def __init__(self):
        self.payload_set = None

    async def scroll_doc(self, doc_id):
        return [{"chunk_index": 0, "text": "hello", "title": "Doc", "metadata": {}, "enabled": True}]

    async def set_payload(self, doc_id, payload):
        self.payload_set = (doc_id, payload)


class FakeIngest:
    def __init__(self, pptx_error=False):
        self.call = None
        self.pptx_call = None
        self._pptx_error = pptx_error

    async def ingest_text(self, text, *, title=None, doc_type="prose", metadata=None, doc_id=None):
        self.call = dict(text=text, title=title, doc_type=doc_type)
        return ("new-doc", 3)

    async def ingest_pptx(self, data, *, title=None, metadata=None, doc_id=None):
        if self._pptx_error:
            raise ValueError("bad pptx")
        self.pptx_call = dict(nbytes=len(data), title=title)
        return ("deck-doc", 5)


def _user():
    return {"id": 2, "email": "u@x.com", "role": "user"}


def _admin():
    return {"id": 1, "email": "a@x.com", "role": "admin"}


@pytest_asyncio.fixture
async def app():
    app = build_app(settings=S)
    app.state.settings = S
    app.state.documents = FakeDocStore()
    app.state.vector_store = FakeVectorStore()
    app.state.ingest = FakeIngest()
    return app


async def _client(app):
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


async def test_documents_forbidden_for_user(app):
    app.dependency_overrides[get_current_user] = _user
    async with await _client(app) as c:
        r = await c.get("/documents", headers={"Authorization": "Bearer x"})
    assert r.status_code == 403


async def test_documents_ok_for_admin(app):
    app.dependency_overrides[get_current_user] = _admin
    async with await _client(app) as c:
        r = await c.get("/documents", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json()["documents"][0]["doc_id"] == "d1"


async def test_toggle_document_admin(app):
    app.dependency_overrides[get_current_user] = _admin
    async with await _client(app) as c:
        r = await c.patch("/documents/d1", json={"enabled": False},
                          headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json()["document"]["enabled"] is False
    assert app.state.documents.toggled is False
    assert app.state.vector_store.payload_set == ("d1", {"enabled": False})


async def test_chunks_404_for_missing_doc(app):
    app.dependency_overrides[get_current_user] = _admin
    async with await _client(app) as c:
        r = await c.get("/documents/missing/chunks", headers={"Authorization": "Bearer x"})
    assert r.status_code == 404


async def test_documents_unauth_401(app):
    async with await _client(app) as c:
        r = await c.get("/documents")
    assert r.status_code == 401


async def test_ingest_admin_ok(app):
    app.dependency_overrides[get_current_user] = _admin
    async with await _client(app) as c:
        r = await c.post("/ingest", json={"text": "hello world", "doc_type": "prose"},
                         headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json() == {"doc_id": "new-doc", "chunks_ingested": 3}
    assert app.state.ingest.call["text"] == "hello world"


async def test_ingest_forbidden_for_user(app):
    app.dependency_overrides[get_current_user] = _user
    async with await _client(app) as c:
        r = await c.post("/ingest", json={"text": "x", "doc_type": "prose"},
                         headers={"Authorization": "Bearer x"})
    assert r.status_code == 403


async def test_ingest_pptx_admin_ok(app):
    app.dependency_overrides[get_current_user] = _admin
    files = {"file": ("deck.pptx", b"PK\x03\x04fake-bytes", "application/vnd.ms-powerpoint")}
    async with await _client(app) as c:
        r = await c.post("/ingest/pptx", files=files, data={"title": "Deck"},
                         headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json() == {"doc_id": "deck-doc", "chunks_ingested": 5}
    assert app.state.ingest.pptx_call["title"] == "Deck"


async def test_ingest_pptx_forbidden_for_user(app):
    app.dependency_overrides[get_current_user] = _user
    files = {"file": ("deck.pptx", b"x", "application/octet-stream")}
    async with await _client(app) as c:
        r = await c.post("/ingest/pptx", files=files, headers={"Authorization": "Bearer x"})
    assert r.status_code == 403


async def test_ingest_pptx_bad_file_422(app):
    app.dependency_overrides[get_current_user] = _admin
    app.state.ingest = FakeIngest(pptx_error=True)
    files = {"file": ("deck.pptx", b"not-a-pptx", "application/octet-stream")}
    async with await _client(app) as c:
        r = await c.post("/ingest/pptx", files=files, headers={"Authorization": "Bearer x"})
    assert r.status_code == 422


async def test_health_open(app):
    async with await _client(app) as c:
        r = await c.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}
