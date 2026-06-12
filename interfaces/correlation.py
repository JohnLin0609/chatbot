"""Match outbound events back to the request that produced them.

A gateway (HTTP or CLI) publishes an inbound event with a unique
`correlation_id`, then awaits the matching outbound event. The OutboundWaiter
runs one background reader over the outbound stream and resolves per-request
futures by correlation_id.
"""

import asyncio
import logging

from redis.asyncio import Redis

from core.config import Settings
from shared import redis_client as rc
from shared.events import OutboundEvent, outbound_from_stream_fields

log = logging.getLogger("correlation")


class OutboundWaiter:
    def __init__(
        self, redis: Redis, settings: Settings, group: str, consumer: str
    ) -> None:
        self._redis = redis
        self._settings = settings
        self._group = group
        self._consumer = consumer
        self._pending: dict[str, asyncio.Future] = {}
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        await rc.ensure_group(
            self._redis, self._settings.outbound_stream, self._group
        )
        self._task = asyncio.create_task(self._reader())

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    def register(self, correlation_id: str) -> asyncio.Future:
        # get_running_loop: register() is only ever called from async handlers;
        # get_event_loop() is deprecated outside a running loop and could bind
        # the future to the wrong loop.
        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[correlation_id] = future
        return future

    async def wait(self, correlation_id: str) -> OutboundEvent:
        future = self._pending.get(correlation_id) or self.register(correlation_id)
        try:
            return await asyncio.wait_for(
                future, timeout=self._settings.reply_timeout_seconds
            )
        finally:
            self._pending.pop(correlation_id, None)

    async def _reader(self) -> None:
        while True:
            try:
                messages = await rc.read_group(
                    self._redis,
                    self._settings.outbound_stream,
                    self._group,
                    self._consumer,
                    block_ms=5000,
                )
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001
                log.exception("outbound reader error")
                await asyncio.sleep(1)
                continue

            for message_id, fields in messages:
                event = outbound_from_stream_fields(fields)
                future = self._pending.get(event.correlation_id)
                if future and not future.done():
                    future.set_result(event)
                await rc.ack(
                    self._redis,
                    self._settings.outbound_stream,
                    self._group,
                    message_id,
                )
