"""End-to-end core pipeline tests (fakeredis + sqlite + fake LLM)."""

import asyncio
import json
import time
import uuid

from sqlalchemy import func, select

from core.facts.extractor import FactExtractor
from core.facts.store import UserMemoryStore
from core.llm.base import ChatServiceError
from core.memory.hot_store import HotStore
from core.persistence.models import Message, Session, UserMemory
from core.pipeline import PipelineDeps, handle_inbound
from core.summary.summarizer import Summarizer
from core.tokens.counter import TokenCounter
from core.tools.loop import ToolRunner
from core.tools.registry import ToolRegistry
from shared.events import InboundEvent, make_session_id
from tests.conftest import FakeChat, FakeEmbedding, FakeVectorStore, make_settings


def _inbound(text: str, user_id="U1", channel="c1") -> InboundEvent:
    return InboundEvent(
        event_id=str(uuid.uuid4()), platform="line", channel_id=channel,
        session_id=make_session_id("line", channel), user_id=user_id, text=text,
        message_id=str(uuid.uuid4()), correlation_id=f"corr-{text}", timestamp=time.time(),
    )


def _deps(settings, redis, sessionmaker, chat, registry=None):
    counter = TokenCounter(settings.tiktoken_encoding)
    hot = HotStore(redis, settings)
    store = UserMemoryStore(redis, settings)
    registry = registry or ToolRegistry()
    return PipelineDeps(
        settings=settings, hot_store=hot, sessionmaker=sessionmaker, chat_service=chat,
        summarizer=Summarizer(settings, chat), token_counter=counter,
        user_memory_store=store, fact_extractor=FactExtractor(settings, chat, counter),
        tool_runner=ToolRunner(chat, registry, settings),
        embedding_service=FakeEmbedding(), vector_store=FakeVectorStore(),
    )


class FactAwareChat:
    """Returns fact JSON for the extraction prompt, summaries for the summary
    prompt, and an echo otherwise."""

    supports_tools = False

    def __init__(self, settings):
        self._fact_prompt = settings.fact_system_prompt
        self._channel_prompt = settings.channel_summary_system_prompt
        self.calls = []

    async def generate_reply(self, key, messages):
        self.calls.append(messages)
        sys = messages[0]["content"] if messages and messages[0]["role"] == "system" else ""
        if sys == self._fact_prompt:
            return json.dumps({
                "facts": [{"key": "name", "value": "小明", "confidence": 0.9}],
                "rolling_summary": "User is 小明.",
            })
        if sys == self._channel_prompt:
            return "channel summary"
        last_user = [m for m in messages if m["role"] == "user"][-1]["content"]
        return f"reply-to:{last_user}"

    async def complete(self, key, messages, tools=None):
        from core.tools.schemas import ChatCompletionResult

        text = await self.generate_reply(key, messages)
        return ChatCompletionResult(text=text, raw_assistant_message={"role": "assistant", "content": text})


# --------------------------------------------------------------- basic
async def test_reply_and_correlation_passthrough(redis, sessionmaker):
    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    out = await handle_inbound(_inbound("hello"), _deps(s, redis, sessionmaker, FakeChat()))
    assert out.status == "ok"
    assert out.text == "reply-to:hello"
    assert out.correlation_id == "corr-hello"


async def test_outbound_carries_reply_message_id(redis, sessionmaker):
    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    out = await handle_inbound(_inbound("hi"), _deps(s, redis, sessionmaker, FakeChat()))
    assert out.reply_message_id is not None
    async with sessionmaker() as db:
        row = (await db.execute(
            select(Message).where(Message.role == "assistant")
        )).scalar_one()
    assert out.reply_message_id == row.id  # points at the persisted assistant reply


async def test_admin_system_prompt_override_applied(redis, sessionmaker):
    from core.persistence import repository as repo

    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000,
                      system_prompt="DEFAULT PERSONA")
    chat = FakeChat()
    deps = _deps(s, redis, sessionmaker, chat)
    async with sessionmaker() as db:
        await repo.upsert_app_setting(db, "system_prompt", "PIRATE MODE")
        await db.commit()
    await handle_inbound(_inbound("ahoy"), deps)
    main_call = [c for c in chat.calls if c[-1]["content"] == "ahoy"][-1]
    assert main_call[0] == {"role": "system", "content": "PIRATE MODE"}


async def test_persists_messages(redis, sessionmaker):
    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    await handle_inbound(_inbound("hi"), _deps(s, redis, sessionmaker, FakeChat()))
    async with sessionmaker() as db:
        count = (await db.execute(select(func.count()).select_from(Message))).scalar()
        sessions = (await db.execute(select(Session))).scalars().all()
    assert count == 2
    assert [x.session_key for x in sessions] == ["line:c1"]


async def test_memory_carries_across_turns(redis, sessionmaker):
    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    chat = FakeChat()
    deps = _deps(s, redis, sessionmaker, chat)
    await handle_inbound(_inbound("first"), deps)
    out = await handle_inbound(_inbound("second"), deps)
    second_call = [c for c in chat.calls if c[-1]["content"] == "second"][-1]
    assert "first" in [m["content"] for m in second_call]
    assert out.text == "reply-to:second"


async def test_llm_error_returns_error_without_persisting(redis, sessionmaker):
    class BoomChat:
        supports_tools = False

        async def generate_reply(self, key, messages):
            raise ChatServiceError("upstream down")

        async def complete(self, key, messages, tools=None):
            raise ChatServiceError("upstream down")

    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    out = await handle_inbound(_inbound("hi"), _deps(s, redis, sessionmaker, BoomChat()))
    assert out.status == "error"
    async with sessionmaker() as db:
        count = (await db.execute(select(func.count()).select_from(Message))).scalar()
    assert count == 0


async def test_cold_backfill_from_postgres(redis, sessionmaker):
    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    deps = _deps(s, redis, sessionmaker, FakeChat())
    await handle_inbound(_inbound("remember"), deps)
    await redis.flushall()
    out = await handle_inbound(_inbound("again"), deps)
    last_main = [c for c in deps.chat_service.calls if c[-1]["content"] == "again"][-1]
    assert "remember" in [m["content"] for m in last_main]
    assert out.status == "ok"


# --------------------------------------------------------------- tier-2
async def test_overflow_folds_channel_summary(redis, sessionmaker):
    from core.persistence.models import Summary

    s = make_settings(context_window_tokens=20, fact_extraction_tokens=100_000)
    deps = _deps(s, redis, sessionmaker, FactAwareChat(make_settings()))
    for t in ["aaa", "bbb", "ccc", "ddd", "eee", "fff"]:
        await handle_inbound(_inbound(t), deps)
    async with sessionmaker() as db:
        summaries = (await db.execute(select(func.count()).select_from(Summary))).scalar()
    assert summaries >= 1  # window overflowed -> channel summary folded


# --------------------------------------------------------------- tier-3
async def test_fact_extraction_populates_user_memory(redis, sessionmaker):
    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=20)
    deps = _deps(s, redis, sessionmaker, FactAwareChat(make_settings()))
    for t in ["hi there friend", "how are you doing today", "tell me a story"]:
        await handle_inbound(_inbound(t), deps)
    async with sessionmaker() as db:
        row = (await db.execute(select(UserMemory).where(UserMemory.user_key == "line:U1"))).scalar_one_or_none()
    assert row is not None
    assert "name" in row.document["facts"]
    assert row.last_extracted_message_id is not None  # cursor advanced


async def test_invariant_messages_preserved_when_window_shrinks(redis, sessionmaker):
    # tier-3 disabled (huge threshold) so cursor never advances; window tiny.
    s = make_settings(context_window_tokens=20, fact_extraction_tokens=10_000_000)
    deps = _deps(s, redis, sessionmaker, FactAwareChat(make_settings()))
    n = 6
    for i in range(n):
        await handle_inbound(_inbound(f"message number {i}"), deps)
    async with sessionmaker() as db:
        msg_count = (await db.execute(select(func.count()).select_from(Message))).scalar()
        row = (await db.execute(select(UserMemory).where(UserMemory.user_key == "line:U1"))).scalar_one_or_none()
    assert msg_count == 2 * n  # all turns durably preserved
    # hot window shrank below the full history
    _summary, turns = await deps.hot_store.load("line:c1")
    assert len(turns) < 2 * n
    # cursor never advanced (no extraction)
    assert row is None or row.last_extracted_message_id is None


async def test_fact_extraction_async_helper(redis, sessionmaker):
    # Drive turns with extraction disabled, then run the async background helper
    # directly (it opens its own session — same path the async branch fires).
    from core.pipeline import _extract_facts_async

    base = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000_000)
    deps = _deps(base, redis, sessionmaker, FactAwareChat(make_settings()))
    for t in ["hi there friend", "how are you doing today"]:
        await handle_inbound(_inbound(t), deps)

    low = make_settings(fact_extraction_tokens=5)
    deps2 = _deps(low, redis, sessionmaker, FactAwareChat(make_settings()))
    await _extract_facts_async(deps2, "line:U1", "U1")

    async with sessionmaker() as db:
        row = (await db.execute(select(UserMemory).where(UserMemory.user_key == "line:U1"))).scalar_one_or_none()
    assert row is not None and "name" in row.document["facts"]
    assert row.last_extracted_message_id is not None


# --------------------------------------------------------------- tier-4 (Adaptive-RAG)
async def test_medium_query_injects_retrieved_knowledge(redis, sessionmaker):
    """With classifier+retriever wired, handle_inbound retrieves and injects the
    knowledge block into the LLM prompt."""
    from core.rag.classifier import MEDIUM
    from core.rag.vector_store import Hit

    class FakeClassifier:
        async def classify(self, q):
            return MEDIUM

    class FakeRetriever:
        async def retrieve(self, q, *, top_k):
            return [Hit(text="Refunds within 30 days.", score=0.9, title="Policy", payload={})]

    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000_000)
    chat = FakeChat()
    deps = _deps(s, redis, sessionmaker, chat)
    deps.classifier = FakeClassifier()
    deps.retriever = FakeRetriever()

    out = await handle_inbound(_inbound("how do refunds work?"), deps)
    assert out.status == "ok"
    # the retrieved chunk reached the model as a system knowledge block
    injected = [m for call in chat.calls for m in call
                if m["role"] == "system" and "Refunds within 30 days." in m["content"]]
    assert injected, "retrieved knowledge was not injected into the prompt"


async def test_eval_trace_logged_with_retrieved_chunks(redis, sessionmaker):
    """A RAG turn writes an eval_trace + one eval_retrieved_chunk (included)."""
    from core.eval.logger import EvalLogger
    from core.persistence.models import EvalRetrievedChunk, EvalTrace
    from core.rag.classifier import MEDIUM
    from core.rag.vector_store import Hit
    from core.tokens.counter import TokenCounter

    class FakeClassifier:
        async def classify(self, q):
            return MEDIUM

    class FakeRetriever:
        async def retrieve(self, q, *, top_k):
            return [Hit(text="Refunds within 30 days.", score=0.9, title="Policy",
                        payload={"doc_id": "d1", "chunk_index": 0})][:top_k]

    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    deps = _deps(s, redis, sessionmaker, FakeChat())
    deps.classifier = FakeClassifier()
    deps.retriever = FakeRetriever()
    deps.eval_logger = EvalLogger(sessionmaker, TokenCounter(s.tiktoken_encoding), s)

    await handle_inbound(_inbound("how do refunds work?"), deps)
    await asyncio.sleep(0.1)  # let the fire-and-forget log_trace task finish

    async with sessionmaker() as db:
        trace = (await db.execute(select(EvalTrace))).scalar_one()
        chunks = (await db.execute(select(EvalRetrievedChunk))).scalars().all()
    assert trace.rag_tier == MEDIUM
    assert trace.query == "how do refunds work?"
    assert trace.reply_text == "reply-to:how do refunds work?"
    assert trace.messages is not None and trace.prompt_tokens
    assert len(chunks) == 1
    assert chunks[0].doc_id == "d1" and chunks[0].included is True


async def test_eval_trace_simple_tier_no_chunks(redis, sessionmaker):
    from core.eval.logger import EvalLogger
    from core.persistence.models import EvalRetrievedChunk, EvalTrace
    from core.rag.classifier import SIMPLE
    from core.tokens.counter import TokenCounter

    class FakeClassifier:
        async def classify(self, q):
            return SIMPLE

    class FakeRetriever:
        async def retrieve(self, q, *, top_k):
            raise AssertionError("simple tier must not retrieve")

    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    deps = _deps(s, redis, sessionmaker, FakeChat())
    deps.classifier = FakeClassifier()
    deps.retriever = FakeRetriever()
    deps.eval_logger = EvalLogger(sessionmaker, TokenCounter(s.tiktoken_encoding), s)

    await handle_inbound(_inbound("hi there"), deps)
    await asyncio.sleep(0.1)

    async with sessionmaker() as db:
        trace = (await db.execute(select(EvalTrace))).scalar_one()
        chunks = (await db.execute(select(EvalRetrievedChunk))).scalars().all()
    assert trace.rag_tier == SIMPLE and chunks == []


async def test_simple_query_injects_nothing(redis, sessionmaker):
    from core.rag.classifier import SIMPLE
    from core.rag.vector_store import Hit

    class FakeClassifier:
        async def classify(self, q):
            return SIMPLE

    class FakeRetriever:
        def __init__(self):
            self.called = False

        async def retrieve(self, q, *, top_k):
            self.called = True
            return [Hit(text="SHOULD NOT APPEAR", score=1.0, title=None, payload={})]

    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000_000)
    chat = FakeChat()
    deps = _deps(s, redis, sessionmaker, chat)
    deps.classifier = FakeClassifier()
    retriever = FakeRetriever()
    deps.retriever = retriever

    await handle_inbound(_inbound("hi there"), deps)
    assert not retriever.called  # simple tier skips retrieval entirely
    leaked = [m for call in chat.calls for m in call if "SHOULD NOT APPEAR" in m["content"]]
    assert not leaked


# --------------------------------------------------------------- tier-4 (tools)
async def test_pipeline_routes_through_tool_loop(redis, sessionmaker):
    """A tool-capable model calls search_knowledge; the pipeline executes it and
    returns the final answer."""
    from core.rag.vector_store import Hit
    from core.tools.schemas import ChatCompletionResult, Tool, ToolCall

    seen_tool_output = {}

    async def fake_search(args, ctx):
        hits = await ctx.vector_store.search([0.0], 5, source="curated")
        seen_tool_output["text"] = hits[0].text
        return hits[0].text

    registry = ToolRegistry()
    registry.register(Tool(name="search_knowledge", description="d",
                           parameters={"type": "object", "properties": {}}, handler=fake_search))

    class ToolChat:
        supports_tools = True

        def __init__(self):
            self._step = 0

        async def generate_reply(self, key, messages):
            return "fallback"

        async def complete(self, key, messages, tools=None):
            self._step += 1
            if self._step == 1 and tools:
                return ChatCompletionResult(
                    text=None,
                    tool_calls=[ToolCall(id="c1", name="search_knowledge", arguments={"query": "refund"})],
                    raw_assistant_message={"role": "assistant", "tool_calls": [
                        {"id": "c1", "type": "function",
                         "function": {"name": "search_knowledge", "arguments": "{}"}}]},
                )
            return ChatCompletionResult(text="Refunds take 30 days.",
                                        raw_assistant_message={"role": "assistant", "content": "Refunds take 30 days."})

    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000_000)
    chat = ToolChat()
    deps = _deps(s, redis, sessionmaker, chat, registry=registry)
    deps.vector_store = FakeVectorStore(hits=[Hit(text="Refund within 30 days", score=0.9, title="Refund", payload={})])

    out = await handle_inbound(_inbound("how do refunds work?"), deps)
    assert out.status == "ok"
    assert out.text == "Refunds take 30 days."
    assert seen_tool_output["text"] == "Refund within 30 days"  # tool actually ran


# ---------------------------------------- error paths (partial failures)
async def test_llm_error_after_retrieval_no_partial_writes(redis, sessionmaker):
    """Retrieval succeeds, then the LLM dies: error outbound, and NOTHING is
    persisted — no db messages, no hot-store turns (pins write ordering)."""
    from core.rag.classifier import MEDIUM
    from core.rag.vector_store import Hit

    class FakeClassifier:
        async def classify(self, q):
            return MEDIUM

    class FakeRetriever:
        def __init__(self):
            self.called = False

        async def retrieve(self, q, *, top_k):
            self.called = True
            return [Hit(text="knowledge", score=0.9, title="Doc", payload={})]

    class BoomChat:
        supports_tools = False

        async def generate_reply(self, key, messages):
            raise ChatServiceError("upstream down")

        async def complete(self, key, messages, tools=None):
            raise ChatServiceError("upstream down")

    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    deps = _deps(s, redis, sessionmaker, BoomChat())
    retriever = FakeRetriever()
    deps.classifier = FakeClassifier()
    deps.retriever = retriever

    out = await handle_inbound(_inbound("question", channel="err1"), deps)

    assert retriever.called  # retrieval really happened first
    assert out.status == "error"
    async with sessionmaker() as db:
        count = (await db.execute(select(func.count()).select_from(Message))).scalar()
    assert count == 0
    _, turns = await deps.hot_store.load(make_session_id("line", "err1"))
    assert turns == []


async def test_retriever_failure_still_replies_without_knowledge(redis, sessionmaker):
    from core.rag.classifier import MEDIUM

    class FakeClassifier:
        async def classify(self, q):
            return MEDIUM

    class BrokenRetriever:
        async def retrieve(self, q, *, top_k):
            raise ConnectionError("qdrant down")

    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    chat = FakeChat()
    deps = _deps(s, redis, sessionmaker, chat)
    deps.classifier = FakeClassifier()
    deps.retriever = BrokenRetriever()

    out = await handle_inbound(_inbound("question", channel="err2"), deps)

    assert out.status == "ok"
    assert out.text == "reply-to:question"
    assert all("knowledge" not in m["content"].lower()
               for call in chat.calls for m in call if m["role"] == "system")
    async with sessionmaker() as db:  # the turn persisted normally
        count = (await db.execute(select(func.count()).select_from(Message))).scalar()
    assert count == 2


async def test_classifier_failure_still_replies(redis, sessionmaker):
    class BrokenClassifier:
        async def classify(self, q):
            raise TimeoutError("classifier LLM stalled")

    class TrackingRetriever:
        def __init__(self):
            self.called = False

        async def retrieve(self, q, *, top_k):
            self.called = True
            return []

    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    deps = _deps(s, redis, sessionmaker, FakeChat())
    deps.classifier = BrokenClassifier()
    deps.retriever = TrackingRetriever()

    out = await handle_inbound(_inbound("question", channel="err3"), deps)
    assert out.status == "ok"
    assert out.text == "reply-to:question"


# ------------------------------------ tool loop through the full pipeline
def _lookup_registry(handler=None):
    from core.tools.schemas import Tool

    async def lookup(args, ctx):
        return f"result-for:{args.get('q', '')}"

    registry = ToolRegistry()
    registry.register(Tool(name="lookup", description="look things up",
                           parameters={"type": "object", "properties": {}},
                           handler=handler or lookup))
    return registry


async def test_tool_round_trip_stacks_messages_and_persists(redis, sessionmaker):
    from core.tools.schemas import ToolCall
    from tests.conftest import ToolCallingFakeChat

    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    chat = ToolCallingFakeChat([ToolCall(id="c1", name="lookup",
                                         arguments={"q": "例外處理"})])
    deps = _deps(s, redis, sessionmaker, chat, registry=_lookup_registry())

    out = await handle_inbound(_inbound("查一下例外處理", channel="t1"), deps)

    assert out.status == "ok"
    assert out.text == "answer: result-for:例外處理"
    # OpenAI stacking contract: 2nd completion sees the verbatim assistant
    # message (with tool_calls) followed by the tool result for that call id.
    second = chat.calls[1]
    assert second[-2]["role"] == "assistant"
    assert second[-2]["tool_calls"][0]["id"] == "c1"
    assert second[-1] == {"role": "tool", "tool_call_id": "c1",
                          "content": "result-for:例外處理"}
    async with sessionmaker() as db:  # final answer persisted as the reply
        row = (await db.execute(
            select(Message).where(Message.role == "assistant")
        )).scalar_one()
    assert row.content == "answer: result-for:例外處理"


async def test_unknown_tool_surfaces_error_to_model(redis, sessionmaker):
    from core.tools.schemas import ToolCall
    from tests.conftest import ToolCallingFakeChat

    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    chat = ToolCallingFakeChat([ToolCall(id="c1", name="no_such_tool", arguments={})])
    deps = _deps(s, redis, sessionmaker, chat, registry=_lookup_registry())

    out = await handle_inbound(_inbound("hi", channel="t2"), deps)

    assert out.status == "ok"  # reply still produced
    tool_msg = [m for m in chat.calls[1] if m["role"] == "tool"][0]
    assert tool_msg["content"] == "error: unknown tool 'no_such_tool'"


async def test_tool_handler_exception_surfaces_error_to_model(redis, sessionmaker):
    from core.tools.schemas import ToolCall
    from tests.conftest import ToolCallingFakeChat

    async def kaboom(args, ctx):
        raise ValueError("kaboom")

    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000)
    chat = ToolCallingFakeChat([ToolCall(id="c1", name="lookup", arguments={})])
    deps = _deps(s, redis, sessionmaker, chat, registry=_lookup_registry(kaboom))

    out = await handle_inbound(_inbound("hi", channel="t3"), deps)

    assert out.status == "ok"
    tool_msg = [m for m in chat.calls[1] if m["role"] == "tool"][0]
    assert tool_msg["content"] == "error: kaboom"


async def test_tool_iteration_cap_forces_convergence(redis, sessionmaker):
    from core.tools.schemas import ToolCall
    from tests.conftest import ToolCallingFakeChat

    s = make_settings(context_window_tokens=10_000, fact_extraction_tokens=10_000,
                      tool_max_iterations=2)
    calls = [ToolCall(id=f"c{i}", name="lookup", arguments={"q": str(i)})
             for i in range(3)]  # one more than the cap
    chat = ToolCallingFakeChat(calls)
    deps = _deps(s, redis, sessionmaker, chat, registry=_lookup_registry())

    out = await handle_inbound(_inbound("hi", channel="t4"), deps)

    assert out.status == "ok"
    # 2 capped iterations with tools, then one final tool-free pass.
    assert [t is not None for t in chat.tools_seen] == [True, True, False]
    assert "result-for:0" in out.text and "result-for:1" in out.text
