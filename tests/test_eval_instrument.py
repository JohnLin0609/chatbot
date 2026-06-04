"""InstrumentedChatService records llm_call telemetry and passes calls through."""

import asyncio

from core.eval.instrument import InstrumentedChatService
from core.tools.schemas import ChatCompletionResult


class RecordingLogger:
    def __init__(self):
        self.calls = []

    async def log_call(self, call_type, **kw):
        self.calls.append({"call_type": call_type, **kw})


class FakeChat:
    supports_tools = True

    async def generate_reply(self, session_id, messages):
        return "the reply"

    async def complete(self, session_id, messages, tools=None):
        return ChatCompletionResult(text="done", tool_calls=[],
                                    raw_assistant_message={"role": "assistant"})


class BoomChat:
    supports_tools = False

    async def generate_reply(self, session_id, messages):
        raise RuntimeError("upstream down")

    async def complete(self, session_id, messages, tools=None):
        raise RuntimeError("upstream down")


async def test_passes_reply_through_and_logs(monkeypatch):
    rec = RecordingLogger()
    svc = InstrumentedChatService(FakeChat(), rec, "classifier")
    out = await svc.generate_reply("classify", [{"role": "user", "content": "hi"}])
    assert out == "the reply"
    assert svc.supports_tools is True
    await asyncio.sleep(0)  # let the fire-and-forget task run
    assert rec.calls and rec.calls[0]["call_type"] == "classifier"
    assert rec.calls[0]["output_text"] == "the reply"
    assert rec.calls[0]["ok"] is True and rec.calls[0]["latency_ms"] >= 0


async def test_complete_logs_result_text():
    rec = RecordingLogger()
    svc = InstrumentedChatService(FakeChat(), rec, "main_reply")
    r = await svc.complete("s", [{"role": "user", "content": "hi"}])
    assert r.text == "done"
    await asyncio.sleep(0)
    assert rec.calls[0]["call_type"] == "main_reply"
    assert rec.calls[0]["output_text"] == "done"


async def test_logger_failure_never_breaks_call():
    class AngryLogger:
        async def log_call(self, *a, **k):
            raise RuntimeError("log fail")

    svc = InstrumentedChatService(FakeChat(), AngryLogger(), "main_reply")
    # the create_task for a failing logger must not surface here
    assert await svc.generate_reply("s", []) == "the reply"
    await asyncio.sleep(0)


async def test_records_error_then_reraises():
    rec = RecordingLogger()
    svc = InstrumentedChatService(BoomChat(), rec, "main_reply")
    raised = False
    try:
        await svc.generate_reply("s", [])
    except RuntimeError:
        raised = True
    assert raised
    await asyncio.sleep(0)
    assert rec.calls[0]["ok"] is False and "upstream down" in rec.calls[0]["error"]
