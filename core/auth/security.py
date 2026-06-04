"""Password hashing (bcrypt) + JWT access tokens (pyjwt)."""

import logging
import os
import time

import bcrypt
import jwt

from core.config import Settings

log = logging.getLogger("auth")

# Ephemeral fallback secret when JWT_SECRET is unset (dev only — tokens do not
# survive a restart). Generated once per process.
_DEV_SECRET = os.urandom(32).hex()
_warned = False


class TokenError(Exception):
    """Raised when a JWT is missing/expired/invalid."""


def _secret(settings: Settings) -> str:
    global _warned
    if settings.jwt_secret:
        return settings.jwt_secret
    if not _warned:
        log.warning("JWT_SECRET is unset; using an ephemeral dev secret "
                    "(tokens will not survive a restart).")
        _warned = True
    return _DEV_SECRET


def hash_password(password: str) -> str:
    # bcrypt only uses the first 72 bytes; truncate to avoid a hard error.
    return bcrypt.hashpw(password.encode()[:72], bcrypt.gensalt()).decode()


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode()[:72], hashed.encode())
    except (ValueError, TypeError):
        return False


def create_access_token(settings: Settings, *, sub: str, role: str) -> str:
    now = int(time.time())
    payload = {
        "sub": str(sub),
        "role": role,
        "iat": now,
        "exp": now + settings.jwt_expiry_minutes * 60,
    }
    return jwt.encode(payload, _secret(settings), algorithm=settings.jwt_algorithm)


def decode_token(settings: Settings, token: str) -> dict:
    try:
        return jwt.decode(token, _secret(settings), algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc
