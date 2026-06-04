"""AppSettingStore: CRUD over the `app_settings` KV table.

Currently backs the admin-editable global system prompt (key "system_prompt").
Wraps a sessionmaker and owns its own transaction, like DocumentStore/UserStore.
"""

from sqlalchemy.ext.asyncio import async_sessionmaker

from core.persistence import repository as repo

SYSTEM_PROMPT_KEY = "system_prompt"


class AppSettingStore:
    def __init__(self, sessionmaker: async_sessionmaker) -> None:
        self._sm = sessionmaker

    async def get(self, key: str) -> str | None:
        async with self._sm() as db:
            return await repo.get_app_setting(db, key)

    async def set(self, key: str, value: str) -> None:
        async with self._sm() as db:
            await repo.upsert_app_setting(db, key, value)
            await db.commit()

    async def delete(self, key: str) -> None:
        async with self._sm() as db:
            await repo.delete_app_setting(db, key)
            await db.commit()
