"""Async Redis connection + thin Streams helpers shared by core and gateways."""

import asyncio

from redis.asyncio import Redis
from redis.exceptions import ResponseError, TimeoutError as RedisTimeoutError


def create_redis(url: str) -> Redis:
    """Create an async Redis client that returns str (not bytes)."""
    return Redis.from_url(url, decode_responses=True)


async def ensure_group(redis: Redis, stream: str, group: str) -> None:
    """Create a consumer group (and the stream) if it does not exist yet.

    Uses MKSTREAM so the stream is created lazily; ignores BUSYGROUP when the
    group already exists.
    """
    try:
        await redis.xgroup_create(name=stream, groupname=group, id="0", mkstream=True)
    except ResponseError as exc:
        if "BUSYGROUP" not in str(exc):
            raise


async def publish(redis: Redis, stream: str, fields: dict[str, str]) -> str:
    """XADD an event; returns the Redis-assigned message id."""
    return await redis.xadd(stream, fields)


async def read_group(
    redis: Redis,
    stream: str,
    group: str,
    consumer: str,
    *,
    count: int = 10,
    block_ms: int = 5000,
):
    """XREADGROUP new (">") messages for a consumer.

    Returns a list of (message_id, fields) tuples, possibly empty on timeout.
    """
    try:
        result = await redis.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=count,
            block=block_ms,
        )
    except (RedisTimeoutError, asyncio.TimeoutError):
        # A blocking read that returns nothing within the window surfaces as a
        # socket read timeout depending on client config; treat as "idle".
        return []
    if not result:
        # Pause briefly on idle reads. Real Redis blocks server-side for
        # block_ms so this adds ~nothing; fakeredis ignores `block` and returns
        # instantly, and without this pause a `while True` reader becomes a
        # tight spinner that starves every other task in the loop.
        await asyncio.sleep(0.01)
        return []
    # result = [(stream_name, [(msg_id, {field: value}), ...])]
    return result[0][1]


async def ack(redis: Redis, stream: str, group: str, message_id: str) -> None:
    await redis.xack(stream, group, message_id)


async def autoclaim(
    redis: Redis,
    stream: str,
    group: str,
    consumer: str,
    *,
    min_idle_ms: int = 60000,
    count: int = 10,
):
    """Reclaim messages pending longer than min_idle_ms from dead consumers.

    Returns a list of (message_id, fields) tuples.
    """
    _cursor, messages, _deleted = await redis.xautoclaim(
        name=stream,
        groupname=group,
        consumername=consumer,
        min_idle_time=min_idle_ms,
        count=count,
    )
    return messages
