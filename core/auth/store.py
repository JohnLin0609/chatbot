"""UserStore: account CRUD over the `users` table. The first account created is
promoted to `admin`."""

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker

from core.auth.security import hash_password, verify_password
from core.persistence.models import User


class DuplicateEmail(Exception):
    """Raised when registering an email that already exists."""


def _to_dict(u: User) -> dict:
    return {"id": u.id, "email": u.email, "role": u.role, "is_active": u.is_active}


class UserStore:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sm = sessionmaker

    async def count(self) -> int:
        async with self._sm() as db:
            return (await db.execute(select(func.count()).select_from(User))).scalar()

    async def create(self, email: str, password: str) -> dict:
        async with self._sm() as db:
            existing = (
                await db.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
            if existing is not None:
                raise DuplicateEmail(email)
            n = (await db.execute(select(func.count()).select_from(User))).scalar()
            role = "admin" if n == 0 else "user"  # first account bootstraps admin
            user = User(email=email, password_hash=hash_password(password), role=role)
            db.add(user)
            await db.commit()
            await db.refresh(user)
            return _to_dict(user)

    async def authenticate(self, email: str, password: str) -> dict | None:
        async with self._sm() as db:
            user = (
                await db.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
        if user is None or not user.is_active:
            return None
        if not verify_password(password, user.password_hash):
            return None
        return _to_dict(user)

    async def get_by_id(self, user_id) -> dict | None:
        try:
            uid = int(user_id)
        except (TypeError, ValueError):
            return None
        async with self._sm() as db:
            user = await db.get(User, uid)
        return _to_dict(user) if (user and user.is_active) else None

    async def get_by_email(self, email: str) -> dict | None:
        async with self._sm() as db:
            user = (
                await db.execute(select(User).where(User.email == email))
            ).scalar_one_or_none()
        return _to_dict(user) if user else None
