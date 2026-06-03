"""Discord adapter: a gateway bot that bridges Discord <-> the core streams.

  python -m interfaces.discord_app    # needs DISCORD_BOT_TOKEN + Message Content Intent

Trigger: replies when @mentioned in a server channel, and to every DM. Reuses the
OutboundWaiter correlation helper (per-message await), and reflects live status as
a single self-cleaning reaction on the user's message (👀 -> 🧠 -> tool emoji ->
✅ / ❌) driven by the worker's pub/sub progress channel.
"""

import asyncio
import logging
import uuid

import discord

from core.config import Settings, get_settings
from interfaces.correlation import OutboundWaiter
from interfaces.discord_helpers import (
    build_inbound,
    chunk_message,
    clean_content,
    emoji_for_progress,
    parse_allowed_guilds,
    reaction_for,
    should_handle,
)
from shared import redis_client as rc
from shared.events import to_stream_fields
from shared.progress import progress_from_message

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("discord_app")


class ChatBotClient(discord.Client):
    def __init__(self, settings: Settings) -> None:
        intents = discord.Intents.default()
        intents.message_content = True  # privileged — enable in the Dev Portal
        super().__init__(intents=intents)
        self._settings = settings
        self._allowed = parse_allowed_guilds(settings.discord_allowed_guilds)
        self._redis = None
        self._waiter: OutboundWaiter | None = None
        self._active: dict[str, discord.Message] = {}  # correlation_id -> message
        self._react: dict[str, str] = {}  # correlation_id -> current emoji
        self._progress_task: asyncio.Task | None = None

    async def setup_hook(self) -> None:
        self._redis = rc.create_redis(self._settings.redis_url)
        self._waiter = OutboundWaiter(
            self._redis,
            self._settings,
            self._settings.discord_consumer_group,
            f"discord-{uuid.uuid4().hex[:8]}",
        )
        await self._waiter.start()
        self._progress_task = asyncio.create_task(self._progress_loop())

    async def on_ready(self) -> None:
        log.info("discord bot ready as %s (id=%s)", self.user, self.user.id)

    async def on_message(self, message: discord.Message) -> None:
        if self.user and message.author.id == self.user.id:
            return
        is_dm = message.guild is None
        mentioned = bool(self.user) and any(
            u.id == self.user.id for u in message.mentions
        )
        guild_id = str(message.guild.id) if message.guild else None
        if not should_handle(
            is_dm=is_dm,
            is_bot=message.author.bot,
            mentioned=mentioned,
            guild_id=guild_id,
            allowed_guilds=self._allowed,
        ):
            return

        text = clean_content(message.content, self.user.id)
        if not text:
            return

        cid = str(uuid.uuid4())
        inbound = build_inbound(
            text=text,
            channel_id=str(message.channel.id),
            user_id=str(message.author.id),
            message_id=str(message.id),
            correlation_id=cid,
        )
        self._waiter.register(cid)
        self._active[cid] = message
        await self._set_reaction(cid, reaction_for("received"))
        await rc.publish(
            self._redis, self._settings.inbound_stream, to_stream_fields(inbound)
        )

        try:
            async with message.channel.typing():
                event = await self._waiter.wait(cid)
        except asyncio.TimeoutError:
            await self._finish(cid, reaction_for("error"))
            await self._reply(message, "(timed out waiting for a reply)")
            return
        except Exception:  # noqa: BLE001 — never crash the bot on one message
            log.exception("on_message failed")
            await self._finish(cid, reaction_for("error"))
            return

        if event.status == "error":
            await self._finish(cid, reaction_for("error"))
            await self._reply(message, f"[error] {event.error or 'unknown error'}")
        else:
            await self._finish(cid, reaction_for("done"))
            await self._reply(message, event.text)

    async def _progress_loop(self) -> None:
        """Subscribe to worker progress and advance the per-message reaction."""
        pubsub = self._redis.pubsub()
        await pubsub.subscribe(self._settings.progress_channel)
        async for msg in pubsub.listen():
            if msg.get("type") != "message":
                continue
            try:
                ev = progress_from_message(msg["data"])
            except Exception:  # noqa: BLE001 — ignore malformed progress
                continue
            if ev.correlation_id not in self._active:
                continue
            await self._set_reaction(
                ev.correlation_id, emoji_for_progress(ev.kind, ev.tool)
            )

    async def _set_reaction(self, cid: str, emoji: str) -> None:
        message = self._active.get(cid)
        if message is None or self._react.get(cid) == emoji:
            return
        old = self._react.get(cid)
        try:
            if old:
                await message.remove_reaction(old, self.user)
            await message.add_reaction(emoji)
            self._react[cid] = emoji
        except discord.HTTPException:
            log.debug("reaction update failed", exc_info=True)

    async def _finish(self, cid: str, emoji: str) -> None:
        await self._set_reaction(cid, emoji)
        self._active.pop(cid, None)
        self._react.pop(cid, None)

    async def _reply(self, message: discord.Message, text: str) -> None:
        for chunk in chunk_message(text) or ["(empty reply)"]:
            try:
                await message.reply(chunk)
            except discord.HTTPException:
                log.exception("failed to send reply")
                break

    async def close(self) -> None:
        if self._progress_task:
            self._progress_task.cancel()
        if self._waiter:
            await self._waiter.stop()
        await super().close()
        if self._redis:
            await self._redis.aclose()


def main() -> None:
    settings = get_settings()
    if not settings.discord_bot_token:
        raise SystemExit("DISCORD_BOT_TOKEN is not set; cannot start the Discord adapter.")
    client = ChatBotClient(settings)
    client.run(settings.discord_bot_token, log_handler=None)


if __name__ == "__main__":
    main()
