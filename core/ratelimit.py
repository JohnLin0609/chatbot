"""Redis fixed-window rate limiter.

One INCR + EXPIRE per hit; the window key rotates every `window_seconds`.
Fails OPEN on Redis errors — losing rate limiting briefly is better than
turning a cache outage into a full API outage.
"""

import logging
import time

log = logging.getLogger("ratelimit")


class RateLimiter:
    def __init__(self, redis, prefix: str = "chat:rl") -> None:
        self._redis = redis
        self._prefix = prefix

    async def hit(self, bucket: str, limit: int, window_seconds: int = 60) -> bool:
        """Record one hit; return True if the caller is within `limit`."""
        window = int(time.time() // window_seconds)
        key = f"{self._prefix}:{bucket}:{window}"
        try:
            count = await self._redis.incr(key)
            if count == 1:
                await self._redis.expire(key, window_seconds * 2)
            return count <= limit
        except Exception:  # noqa: BLE001 — fail open
            log.warning("rate limiter unavailable; allowing request", exc_info=True)
            return True
