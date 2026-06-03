"""Redis hot store: recent turns + running summary per session.

Layout (keys prefixed by settings.redis_key_prefix):
  {prefix}:session:{session_key}:turns    LIST of JSON {role, content, ts}
  {prefix}:session:{session_key}:summary  STRING JSON {text, turn_count, covers_through_message_id}

Both keys' TTL is refreshed on every write. A cold/expired session is rebuilt
from Postgres by the pipeline (see backfill()).
"""

import json
import time

from redis.asyncio import Redis

from core.config import Settings


class HotStore:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self._redis = redis
        self._settings = settings

    # ------------------------------------------------------------------ keys
    def _turns_key(self, session_key: str) -> str:
        return f"{self._settings.redis_key_prefix}:session:{session_key}:turns"

    def _summary_key(self, session_key: str) -> str:
        return f"{self._settings.redis_key_prefix}:session:{session_key}:summary"

    # --------------------------------------------------------------- read
    async def load(self, session_key: str) -> tuple[dict | None, list[dict]]:
        """Return (summary_dict|None, turns oldest-first)."""
        raw_summary = await self._redis.get(self._summary_key(session_key))
        summary = json.loads(raw_summary) if raw_summary else None
        raw_turns = await self._redis.lrange(self._turns_key(session_key), 0, -1)
        turns = [json.loads(t) for t in raw_turns]
        return summary, turns

    async def exists(self, session_key: str) -> bool:
        return bool(await self._redis.exists(self._turns_key(session_key)))

    # Coarse backstop against unbounded growth if overflow-folding ever lags.
    # Normal trimming to the token window happens in the pipeline via
    # replace_turns(); this is only a safety valve.
    _MAX_MESSAGES = 1000

    # --------------------------------------------------------------- write
    async def append_turn(
        self,
        session_key: str,
        user_text: str,
        assistant_text: str,
        user_id: str | None = None,
    ) -> None:
        key = self._turns_key(session_key)
        now = time.time()
        user = json.dumps(
            {"role": "user", "content": user_text, "ts": now, "user_id": user_id}
        )
        assistant = json.dumps(
            {"role": "assistant", "content": assistant_text, "ts": now, "user_id": None}
        )
        pipe = self._redis.pipeline()
        pipe.rpush(key, user, assistant)
        pipe.ltrim(key, -self._MAX_MESSAGES, -1)
        pipe.expire(key, self._settings.hot_ttl_seconds)
        await pipe.execute()

    async def set_summary(self, session_key: str, summary: dict) -> None:
        await self._redis.set(
            self._summary_key(session_key),
            json.dumps(summary),
            ex=self._settings.hot_ttl_seconds,
        )

    async def replace_turns(self, session_key: str, turns: list[dict]) -> None:
        """Overwrite the turns list (used after summarisation trims old turns)."""
        key = self._turns_key(session_key)
        pipe = self._redis.pipeline()
        pipe.delete(key)
        if turns:
            pipe.rpush(key, *[json.dumps(t) for t in turns])
            pipe.expire(key, self._settings.hot_ttl_seconds)
        await pipe.execute()

    async def backfill(
        self, session_key: str, summary: dict | None, turns: list[dict]
    ) -> None:
        """Populate the hot store from durable storage on a cold miss."""
        if summary is not None:
            await self.set_summary(session_key, summary)
        await self.replace_turns(session_key, turns)
