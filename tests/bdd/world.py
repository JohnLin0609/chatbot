"""Sync facades over the async stack for pytest-bdd steps.

pytest-bdd has no async step support, and sync scenarios can't consume
pytest-asyncio fixtures — so each scenario gets a World that owns a
persistent event loop (asyncio.Runner) and builds its own fakes via
tests/factories.py. Steps call plain sync verbs; the World runs the async
machinery underneath.

World     — drives the core pipeline directly (handle_inbound).
ApiWorld  — drives the HTTP app end-to-end: an in-loop worker pump consumes
            the inbound stream and publishes outbound, so /chat exercises
            gateway -> stream -> pipeline -> stream -> gateway for real.
"""

import asyncio
import time
import uuid

import httpx
from httpx import ASGITransport
from sqlalchemy import select

from core.auth.store import UserStore
from core.background import drain
from core.eval.logger import EvalLogger
from core.feedback.store import FeedbackStore
from core.persistence.db import create_sessionmaker
from core.persistence.models import EvalRetrievedChunk, Message, Session, Summary
from core.pipeline import handle_inbound
from core.rag.classifier import MEDIUM
from core.rag.vector_store import Hit
from core.ratelimit import RateLimiter
from core.session.finalizer import sweep_idle_sessions
from interfaces.api_app import build_app
from interfaces.correlation import OutboundWaiter
from interfaces.worker import run_once
from shared import redis_client as rc
from shared.events import InboundEvent, make_session_id
from tests.conftest import FakeChat, make_settings
from tests.factories import build_deps, new_fake_redis, new_sqlite_engine


class _TierClassifier:
    def __init__(self, tier):
        self.tier = tier

    async def classify(self, q):
        return self.tier


class _TrackingRetriever:
    def __init__(self, hits, fail=False):
        self._hits = hits
        self._fail = fail
        self.called = False

    async def retrieve(self, q, *, top_k):
        self.called = True
        if self._fail:
            raise ConnectionError("knowledge base unavailable")
        return self._hits[:top_k]


class _TrackingReranker:
    def __init__(self):
        self.called = False

    async def rerank(self, q, hits, top_k):
        self.called = True
        return hits[:top_k]


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
        # Real eval logging, like production (default settings have it enabled).
        self.deps.eval_logger = EvalLogger(
            self.sessionmaker, self.deps.token_counter, self.settings
        )
        self.last_outbound = None
        self.retriever = None
        self.reranker = None

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

        async def _turn():
            out = await handle_inbound(inbound, self.deps)
            await drain()  # flush fire-and-forget eval logging
            return out

        self.last_outbound = self.run(_turn())
        return self.last_outbound

    @property
    def last_reply(self) -> str | None:
        return self.last_outbound.text if self.last_outbound else None

    @property
    def last_prompt_messages(self) -> list[dict]:
        """The message list sent to the LLM on the most recent main reply."""
        return self.chat.calls[-1] if self.chat.calls else []

    def prompt_text(self) -> str:
        return "\n".join(m["content"] for m in self.last_prompt_messages
                         if m.get("content"))

    # ------------------------------------------------------------ RAG wiring
    def ingest_document(self, title: str, content: str, *, tier=MEDIUM):
        hit = Hit(text=content, score=0.9, title=title,
                  payload={"doc_id": title, "chunk_index": 0})
        self.wire_rag(hits=[hit], tier=tier)

    def wire_rag(self, *, hits=None, tier=MEDIUM, fail=False):
        self.retriever = _TrackingRetriever(hits or [], fail=fail)
        self.reranker = _TrackingReranker()
        self.deps.classifier = _TierClassifier(tier)
        self.deps.retriever = self.retriever
        self.deps.reranker = self.reranker

    # ------------------------------------------------------- memory / session
    def expire_hot_cache(self):
        """Simulate the session hot cache expiring (worst case: all of Redis)."""
        self.run(self.redis.flushall())

    def run_idle_sweeper(self) -> int:
        return self.run(sweep_idle_sessions(self.deps))

    # ------------------------------------------------------------- inspection
    def db_rows(self, model):
        async def _q():
            async with self.sessionmaker() as db:
                return list((await db.execute(select(model))).scalars())

        return self.run(_q())

    def db_messages(self):
        return self.db_rows(Message)

    def db_summaries(self):
        return self.db_rows(Summary)

    def db_sessions(self):
        return self.db_rows(Session)

    def eval_chunks(self):
        return self.db_rows(EvalRetrievedChunk)

    def close(self):
        self.run(self.redis.aclose())
        self.run(self._engine.dispose())
        self._runner.close()


class ApiWorld(World):
    """Drives the FastAPI app over ASGI with a real OutboundWaiter and an
    in-loop worker pump — /chat goes through the streams like production."""

    def __init__(self, **settings_overrides):
        overrides = dict(jwt_secret="bdd-secret", reply_timeout_seconds=5.0)
        overrides.update(settings_overrides)
        super().__init__(**overrides)
        self.app = build_app(settings=self.settings)
        st = self.app.state
        st.settings = self.settings
        st.redis = self.redis
        st.user_store = UserStore(self.sessionmaker)
        st.feedback = FeedbackStore(self.sessionmaker)
        st.sessionmaker = self.sessionmaker
        st.limiter = RateLimiter(self.redis, "bdd:rl")
        self._waiter = OutboundWaiter(
            self.redis, self.settings, self.settings.http_consumer_group, "bdd-api"
        )
        self.run(self._waiter.start())
        st.waiter = self._waiter
        self._client = httpx.AsyncClient(
            transport=ASGITransport(app=self.app), base_url="http://t"
        )
        self._pump = self.run(self._start_pump())
        self.token: str | None = None
        self.last_response: httpx.Response | None = None
        self.last_reply_message_id: int | None = None

    async def _start_pump(self):
        await rc.ensure_group(
            self.redis, self.settings.inbound_stream, self.settings.core_consumer_group
        )

        async def pump():
            while True:
                await run_once(self.redis, self.deps, self.settings,
                               "bdd-worker", block_ms=10)

        return asyncio.create_task(pump())

    # --------------------------------------------------------------- verbs
    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.token}"} if self.token else {}

    def post(self, path: str, json: dict | None = None) -> httpx.Response:
        self.last_response = self.run(
            self._client.post(path, json=json, headers=self._headers())
        )
        return self.last_response

    def get(self, path: str) -> httpx.Response:
        self.last_response = self.run(
            self._client.get(path, headers=self._headers())
        )
        return self.last_response

    def register(self, email: str, password: str = "password123") -> httpx.Response:
        r = self.post("/auth/register", {"email": email, "password": password})
        if r.status_code == 200:
            self.token = r.json()["access_token"]
        return r

    def login(self, email: str, password: str = "password123") -> httpx.Response:
        r = self.post("/auth/login", {"email": email, "password": password})
        if r.status_code == 200:
            self.token = r.json()["access_token"]
        return r

    def send_chat(self, message: str) -> httpx.Response:
        # named send_chat: `self.chat` is the LLM fake inherited from World
        r = self.post("/chat", {"message": message})
        if r.status_code == 200:
            self.last_reply_message_id = r.json()["reply_message_id"]
        return r

    def rate_reply(self, rating: int) -> httpx.Response:
        return self.post(f"/messages/{self.last_reply_message_id}/feedback",
                         {"rating": rating})

    def close(self):
        async def _shutdown():
            self._pump.cancel()
            try:
                await self._pump
            except asyncio.CancelledError:
                pass
            await self._waiter.stop()
            await self._client.aclose()

        self.run(_shutdown())
        super().close()
