"""CLI fake-adapter: drive the core through the real async stream path.

  python -m interfaces.cli                    # interactive, waits for replies
  python -m interfaces.cli --session line:c1  # custom session
  python -m interfaces.cli --fire-and-forget  # publish only, don't wait
"""

import argparse
import asyncio
import sys
import time
import uuid

from core.config import get_settings
from shared import redis_client as rc
from shared.events import InboundEvent, make_session_id, to_stream_fields
from interfaces.correlation import OutboundWaiter


def _split_session(session_id: str) -> tuple[str, str]:
    if ":" in session_id:
        platform, channel_id = session_id.split(":", 1)
        return platform, channel_id
    return "cli", session_id


async def run(session: str, fire_and_forget: bool) -> None:
    settings = get_settings()
    redis = rc.create_redis(settings.redis_url)
    platform, channel_id = _split_session(session)
    session_id = make_session_id(platform, channel_id)

    waiter = None
    if not fire_and_forget:
        waiter = OutboundWaiter(
            redis, settings, settings.cli_consumer_group, f"cli-{uuid.uuid4().hex[:8]}"
        )
        await waiter.start()

    print(f"session={session_id}  (Ctrl-D to quit)")
    loop = asyncio.get_event_loop()
    try:
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            text = line.strip()
            if not text:
                continue

            correlation_id = str(uuid.uuid4())
            inbound = InboundEvent(
                event_id=str(uuid.uuid4()),
                platform=platform,
                channel_id=channel_id,
                session_id=session_id,
                user_id="cli-user",
                text=text,
                message_id=str(uuid.uuid4()),
                correlation_id=correlation_id,
                timestamp=time.time(),
            )
            if waiter:
                waiter.register(correlation_id)
            await rc.publish(redis, settings.inbound_stream, to_stream_fields(inbound))

            if not waiter:
                print("(sent)")
                continue
            try:
                event = await waiter.wait(correlation_id)
            except asyncio.TimeoutError:
                print("(timed out waiting for reply)")
                continue
            if event.status == "error":
                print(f"[error] {event.error}")
            else:
                print(f"bot> {event.text}")
    finally:
        if waiter:
            await waiter.stop()
        await redis.aclose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--session", default="cli:local")
    parser.add_argument("--fire-and-forget", action="store_true")
    args = parser.parse_args()
    try:
        asyncio.run(run(args.session, args.fire_and_forget))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
