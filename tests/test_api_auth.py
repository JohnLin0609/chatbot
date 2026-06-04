"""Auth endpoints via httpx ASGITransport (shares the async loop with the
sqlite sessionmaker fixture). app.state is set directly, bypassing lifespan."""

import httpx
import pytest_asyncio
from httpx import ASGITransport

from core.auth.store import UserStore
from interfaces.api_app import build_app
from tests.conftest import make_settings

S = make_settings(jwt_secret="api-secret")


@pytest_asyncio.fixture
async def client(sessionmaker):
    app = build_app(settings=S)
    app.state.settings = S
    app.state.user_store = UserStore(sessionmaker)
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


async def test_register_first_user_is_admin(client):
    r = await client.post("/auth/register", json={"email": "a@x.com", "password": "password1"})
    assert r.status_code == 200
    body = r.json()
    assert body["user"]["role"] == "admin"
    assert body["access_token"]
    assert body["token_type"] == "bearer"


async def test_register_duplicate_409(client):
    await client.post("/auth/register", json={"email": "a@x.com", "password": "password1"})
    r = await client.post("/auth/register", json={"email": "a@x.com", "password": "password2"})
    assert r.status_code == 409


async def test_register_short_password_422(client):
    r = await client.post("/auth/register", json={"email": "a@x.com", "password": "short"})
    assert r.status_code == 422


async def test_login_and_me(client):
    await client.post("/auth/register", json={"email": "a@x.com", "password": "password1"})
    r = await client.post("/auth/login", json={"email": "a@x.com", "password": "password1"})
    assert r.status_code == 200
    token = r.json()["access_token"]

    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["email"] == "a@x.com"


async def test_login_bad_password_401(client):
    await client.post("/auth/register", json={"email": "a@x.com", "password": "password1"})
    r = await client.post("/auth/login", json={"email": "a@x.com", "password": "nope12345"})
    assert r.status_code == 401


async def test_me_without_token_401(client):
    assert (await client.get("/auth/me")).status_code == 401


async def test_me_bad_token_401(client):
    r = await client.get("/auth/me", headers={"Authorization": "Bearer garbage"})
    assert r.status_code == 401
