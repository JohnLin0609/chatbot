"""UserStore: first-user-admin, duplicate guard, auth, lookups (sqlite)."""

import pytest

from core.auth.store import DuplicateEmail, UserStore


async def test_first_user_is_admin_rest_are_users(sessionmaker):
    store = UserStore(sessionmaker)
    first = await store.create("a@x.com", "password1")
    second = await store.create("b@x.com", "password2")
    assert first["role"] == "admin"
    assert second["role"] == "user"


async def test_duplicate_email_rejected(sessionmaker):
    store = UserStore(sessionmaker)
    await store.create("a@x.com", "password1")
    with pytest.raises(DuplicateEmail):
        await store.create("a@x.com", "password2")


async def test_authenticate(sessionmaker):
    store = UserStore(sessionmaker)
    await store.create("a@x.com", "password1")
    assert await store.authenticate("a@x.com", "password1") is not None
    assert await store.authenticate("a@x.com", "wrong") is None
    assert await store.authenticate("missing@x.com", "password1") is None


async def test_get_by_id_and_email(sessionmaker):
    store = UserStore(sessionmaker)
    u = await store.create("a@x.com", "password1")
    assert (await store.get_by_id(u["id"]))["email"] == "a@x.com"
    assert (await store.get_by_email("a@x.com"))["id"] == u["id"]
    assert await store.get_by_id(999) is None
    assert await store.get_by_id("not-int") is None
