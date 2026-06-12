"""Core worker: consume inbound events, run the pipeline, publish outbound.

Run as a standalone process:  python -m interfaces.worker
"""

import asyncio
import logging
import socket

from core.background import drain
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
    # Ensure the RAG collection exists (used by the search_knowledge tool).
    try:
        await deps.vector_store.ensure_collection()
    except Exception:  # noqa: BLE001 — Qdrant optional; tool degrades if absent
        log.warning("could not ensure Qdrant collection (RAG tool may be unavailable)")
    log.info("worker %s consuming %s", consumer, settings.inbound_stream)

    if settings.session_finalize_enabled:
        asyncio.create_task(_sweeper(deps, settings))
        log.info("session sweeper started (every %ds, idle %ds)",
                 settings.session_sweep_interval_seconds,
                 settings.session_finalize_idle_seconds)

    while True:
        await run_once(redis, deps, settings, consumer)


async def run_once(redis, deps, settings, consumer, *,
                   autoclaim_min_idle_ms: int = 60000, block_ms: int = 5000) -> int:
    """One scheduling pass: reclaim messages abandoned by crashed workers,
    then read new ones. Returns how many messages were attempted."""
    attempted = 0
    claimed = await rc.autoclaim(
        redis, settings.inbound_stream, settings.core_consumer_group, consumer,
        min_idle_ms=autoclaim_min_idle_ms,
    )
    for message_id, fields in claimed:
        await _safe_process(redis, deps, settings, message_id, fields)
        attempted += 1

    messages = await rc.read_group(
        redis,
        settings.inbound_stream,
        settings.core_consumer_group,
        consumer,
        block_ms=block_ms,
    )
    for message_id, fields in messages:
        await _safe_process(redis, deps, settings, message_id, fields)
        attempted += 1
    return attempted


async def _safe_process(redis, deps, settings, message_id, fields) -> None:
    try:
        await _process(redis, deps, settings, message_id, fields)
    except Exception:  # noqa: BLE001 — keep the worker alive; leave msg unacked for retry
        log.exception("pipeline failed for message %s (left pending)", message_id)


async def _sweeper(deps, settings) -> None:
    """Periodically finalise idle sessions (fold into tier-2/3 durable memory)."""
    from core.session.finalizer import sweep_idle_sessions

    while True:
        try:
            n = await sweep_idle_sessions(deps)
            if n:
                log.info("session sweeper finalised %d session(s)", n)
        except Exception:  # noqa: BLE001 — keep the sweeper alive
            log.exception("session sweeper error")
        await asyncio.sleep(settings.session_sweep_interval_seconds)


async def _main() -> None:
    try:
        await run()
    finally:
        # Flush fire-and-forget work (eval traces, async fact extraction)
        # before the loop dies, so shutdown doesn't drop them silently.
        await drain()


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except KeyboardInterrupt:
        log.info("worker stopped")
