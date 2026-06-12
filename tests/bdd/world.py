"""Sync facade over the async pipeline for pytest-bdd steps.

pytest-bdd has no async step support, and sync tests can't consume
pytest-asyncio fixtures — so each scenario gets a World that owns a
persistent event loop (asyncio.Runner) and builds its own fakes via
tests/factories.py. Steps call plain sync verbs; the World runs the
async machinery underneath.
"""

import time
import uuid

import asyncio

from core.persistence.db import create_sessionmaker
from core.pipeline import handle_inbound
from shared.events import InboundEvent, make_session_id
from tests.conftest import FakeChat, make_settings
from tests.factories import build_deps, new_fake_redis, new_sqlite_engine


class World:
    def __init__(self, chat=None, **settings_overrides):
        overrides = dict(context_window_tokens=10_000, fact_extraction_tokens=10_000)
        overrides.update(settings_overrides)
        self._runner = asyncio.Runner()
        self.settings = make_settings(**overrides)
        self.redis = new_fake_redis()
        self._engine = self.run(new_sqlite_engine())
        self.sessionmaker = create_sessionmaker(self._engine)
        self.chat = chat or FakeChat()
        self.deps = build_deps(self.settings, self.redis, self.sessionmaker, self.chat)
        self.last_outbound = None

    def run(self, coro):
        """Escape hatch: run any coroutine on the World's loop."""
        return self._runner.run(coro)

    # ------------------------------------------------------- domain verbs
    def user_says(self, text: str, user_id: str = "U1", channel: str = "c1"):
        inbound = InboundEvent(
            event_id=str(uuid.uuid4()), platform="line", channel_id=channel,
            session_id=make_session_id("line", channel), user_id=user_id,
            text=text, message_id=str(uuid.uuid4()),
            correlation_id=f"corr-{uuid.uuid4().hex[:8]}", timestamp=time.time(),
        )
        self.last_outbound = self.run(handle_inbound(inbound, self.deps))
        return self.last_outbound

    @property
    def last_reply(self) -> str | None:
        return self.last_outbound.text if self.last_outbound else None

    @property
    def last_prompt_messages(self) -> list[dict]:
        """The message list sent to the LLM on the most recent main reply."""
        return self.chat.calls[-1] if self.chat.calls else []

    def close(self):
        self.run(self.redis.aclose())
        self.run(self._engine.dispose())
        self._runner.close()
