"""UserMemoryStore: Postgres-authoritative per-user memory with a Redis mirror.

Postgres is the source of truth (including the extraction cursor); Redis is a
read-through cache for fast prompt assembly.
"""

from datetime import datetime, timezone

from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from core.config import Settings
from core.facts.schema import UserMemoryDocument
from core.persistence import repository as repo


class UserMemoryStore:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self._redis = redis
        self._settings = settings

    def _key(self, user_key: str) -> str:
        return f"{self._settings.redis_key_prefix}:user:{user_key}:memory"

    async def _mirror(self, user_key: str, doc: UserMemoryDocument) -> None:
        await self._redis.set(
            self._key(user_key),
            doc.model_dump_json(),
            ex=self._settings.hot_ttl_seconds,
        )

    async def load(self, db: AsyncSession, user_key: str) -> UserMemoryDocument:
        raw = await self._redis.get(self._key(user_key))
        if raw:
            return UserMemoryDocument.model_validate_json(raw)
        row = await repo.get_user_memory(db, user_key)
        doc = (
            UserMemoryDocument.model_validate(row.document)
            if row
            else UserMemoryDocument.empty(user_key)
        )
        await self._mirror(user_key, doc)
        return doc

    async def save(
        self,
        db: AsyncSession,
        user_key: str,
        doc: UserMemoryDocument,
        last_extracted_message_id: int | None = None,
    ) -> None:
        await repo.upsert_user_memory(
            db, user_key, doc.to_json(), last_extracted_message_id
        )
        await self._mirror(user_key, doc)

    async def get_cursor(self, db: AsyncSession, user_key: str) -> int | None:
        row = await repo.get_user_memory(db, user_key)
        return row.last_extracted_message_id if row else None

    async def set_cursor(
        self, db: AsyncSession, user_key: str, message_id: int
    ) -> None:
        doc = await self.load(db, user_key)
        await self.save(db, user_key, doc, last_extracted_message_id=message_id)

    async def bump_last_used(
        self, db: AsyncSession, user_key: str, keys: list[str]
    ) -> None:
        if not keys:
            return
        doc = await self.load(db, user_key)
        now = datetime.now(timezone.utc)
        changed = False
        for key in keys:
            if key in doc.facts:
                doc.facts[key].last_used_at = now
                changed = True
        if changed:
            await self.save(db, user_key, doc)
