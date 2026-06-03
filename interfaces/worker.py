"""Core worker: consume inbound events, run the pipeline, publish outbound.

Run as a standalone process:  python -m interfaces.worker
"""

import asyncio
import logging
import socket

from core.config import get_settings
from core.pipeline import handle_inbound
from core.runtime import build_pipeline_deps
from shared import redis_client as rc
from shared.events import inbound_from_stream_fields, to_stream_fields

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("worker")


async def _process(redis, deps, settings, message_id, fields) -> None:
    inbound = inbound_from_stream_fields(fields)
    outbound = await handle_inbound(inbound, deps)
    await rc.publish(redis, settings.outbound_stream, to_stream_fields(outbound))
    await rc.ack(redis, settings.inbound_stream, settings.core_consumer_group, message_id)
    log.info("handled %s session=%s status=%s", inbound.event_id, inbound.session_id, outbound.status)


async def run() -> None:
    settings = get_settings()
    redis = rc.create_redis(settings.redis_url)
    deps = build_pipeline_deps(settings, redis)
    consumer = f"worker-{socket.gethostname()}-{id(object()) & 0xffff}"

    await rc.ensure_group(redis, settings.inbound_stream, settings.core_consumer_group)
    log.info("worker %s consuming %s", consumer, settings.inbound_stream)

    while True:
        # Reclaim messages abandoned by crashed workers, then read new ones.
        claimed = await rc.autoclaim(
            redis, settings.inbound_stream, settings.core_consumer_group, consumer
        )
        for message_id, fields in claimed:
            await _safe_process(redis, deps, settings, message_id, fields)

        messages = await rc.read_group(
            redis,
            settings.inbound_stream,
            settings.core_consumer_group,
            consumer,
            block_ms=5000,
        )
        for message_id, fields in messages:
            await _safe_process(redis, deps, settings, message_id, fields)


async def _safe_process(redis, deps, settings, message_id, fields) -> None:
    try:
        await _process(redis, deps, settings, message_id, fields)
    except Exception:  # noqa: BLE001 — keep the worker alive; leave msg unacked for retry
        log.exception("pipeline failed for message %s (left pending)", message_id)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        log.info("worker stopped")
