"""Password hashing + JWT encode/decode."""

import time

import pytest

from core.auth.security import (
    TokenError,
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)
from tests.conftest import make_settings

S = make_settings(jwt_secret="unit-secret", jwt_expiry_minutes=60)


def test_hash_and_verify():
    h = hash_password("correct horse battery staple")
    assert h != "correct horse battery staple"
    assert verify_password("correct horse battery staple", h)
    assert not verify_password("wrong", h)


def test_verify_bad_hash_is_false():
    assert verify_password("x", "not-a-bcrypt-hash") is False


def test_token_round_trip():
    tok = create_access_token(S, sub="42", role="admin")
    payload = decode_token(S, tok)
    assert payload["sub"] == "42"
    assert payload["role"] == "admin"


def test_garbage_token_raises():
    with pytest.raises(TokenError):
        decode_token(S, "not.a.jwt")


def test_expired_token_raises():
    expired = make_settings(jwt_secret="unit-secret", jwt_expiry_minutes=-1)
    tok = create_access_token(expired, sub="1", role="user")
    with pytest.raises(TokenError):
        decode_token(S, tok)


def test_wrong_secret_raises():
    tok = create_access_token(S, sub="1", role="user")
    other = make_settings(jwt_secret="different-secret")
    with pytest.raises(TokenError):
        decode_token(other, tok)
