"""FastAPI auth dependencies. Reads settings + user_store from app.state, so
they can be overridden in tests via app.dependency_overrides."""

from fastapi import Depends, HTTPException, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.auth.security import TokenError, decode_token

_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if creds is None:
        raise HTTPException(status_code=401, detail="Not authenticated")
    settings = request.app.state.settings
    store = request.app.state.user_store
    try:
        payload = decode_token(settings, creds.credentials)
    except TokenError:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    user = await store.get_by_id(payload.get("sub"))
    if user is None:
        raise HTTPException(status_code=401, detail="User not found or inactive")
    return user


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin privileges required")
    return user
