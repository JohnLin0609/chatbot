"""New console endpoints: session delete, system prompt, feedback, reply id."""

import fakeredis.aioredis
import httpx
import pytest_asyncio
from httpx import ASGITransport

from core.auth.deps import get_current_user
from core.eval.golden_store import GoldenStore
from core.feedback.store import FeedbackStore
from core.persistence import repository as repo
from core.settings.store import AppSettingStore
from interfaces.api_app import build_app
from shared.events import OutboundEvent
from tests.conftest import make_settings

S = make_settings(jwt_secret="api-secret", system_prompt="DEFAULT PERSONA")


class FakeWaiter:
    def __init__(self, *a, **k):
        pass

    async def start(self):
        pass

    async def stop(self):
        pass

    def register(self, cid):
        return None

    async def wait(self, cid):
        return OutboundEvent(
            event_id="o1", in_reply_to="e1", platform="web", channel_id="7:t1",
            session_id="web:7:t1", correlation_id=cid, text="pong",
            reply_message_id=42, status="ok", timestamp=0.0,
        )


def _user():
    return {"id": 7, "email": "u@x.com", "role": "user"}


def _admin():
    return {"id": 1, "email": "a@x.com", "role": "admin"}


class FakeJudgeRunner:
    async def run_batch(self, limit=None):
        return {"judged": 3, "skipped": 0, "remaining": 0, "judge_run_id": "run123"}

    async def status(self):
        return {"total_traces": 3, "judged": 3, "unjudged": 0,
                "avg_scores": {"answer_relevance": 0.9}}


class FakeGoldenRunner:
    async def run(self, k_values=None):
        return {"run_id": 1, "num_queries": 2, "k_values": k_values or [1, 3, 5],
                "aggregate": {"recall": {"3": 0.8}, "correctness": 0.75}}

    async def latest_run(self):
        return {"run_id": 1, "num_queries": 2, "aggregate": {"correctness": 0.75},
                "results": []}


@pytest_asyncio.fixture
async def app(sessionmaker):
    app = build_app(settings=S)
    app.state.settings = S
    app.state.redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    app.state.waiter = FakeWaiter()
    app.state.sessionmaker = sessionmaker
    app.state.app_settings = AppSettingStore(sessionmaker)
    app.state.feedback = FeedbackStore(sessionmaker)
    app.state.judge_runner = FakeJudgeRunner()
    app.state.golden_store = GoldenStore(sessionmaker)
    app.state.golden_runner = FakeGoldenRunner()
    return app


async def _client(app):
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://t")


# ---------------------------------------------------------------- chat reply id
async def test_chat_returns_reply_message_id(app):
    app.dependency_overrides[get_current_user] = _user
    async with await _client(app) as c:
        r = await c.post("/chat", json={"message": "hi", "conversation_id": "t1"},
                         headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json()["reply_message_id"] == 42


# ---------------------------------------------------------------- session delete
async def test_delete_session_requires_auth(app):
    async with await _client(app) as c:
        r = await c.delete("/sessions/c1")
    assert r.status_code == 401


async def test_delete_session_removes_own_session(app):
    app.dependency_overrides[get_current_user] = _user
    async with app.state.sessionmaker() as db:
        s = await repo.ensure_session(db, "web:7:c1", "web", "7:c1")
        await repo.append_message(db, s.id, "user", "hi", user_id="7")
        await db.commit()
        sid = s.id
    async with await _client(app) as c:
        r = await c.delete("/sessions/c1", headers={"Authorization": "Bearer x"})
    assert r.status_code == 204
    async with app.state.sessionmaker() as db:
        assert await repo.load_recent(db, sid, limit=10) == []


# ---------------------------------------------------------------- system prompt
async def test_system_prompt_admin_gated(app):
    app.dependency_overrides[get_current_user] = _user
    async with await _client(app) as c:
        assert (await c.get("/admin/system-prompt",
                            headers={"Authorization": "Bearer x"})).status_code == 403
        assert (await c.put("/admin/system-prompt", json={"prompt": "x"},
                            headers={"Authorization": "Bearer x"})).status_code == 403


async def test_system_prompt_get_set_reset(app):
    app.dependency_overrides[get_current_user] = _admin
    async with await _client(app) as c:
        # default first
        r = await c.get("/admin/system-prompt", headers={"Authorization": "Bearer x"})
        assert r.json() == {"prompt": "DEFAULT PERSONA", "is_default": True,
                            "default": "DEFAULT PERSONA"}
        # set an override
        r = await c.put("/admin/system-prompt", json={"prompt": "PIRATE MODE"},
                        headers={"Authorization": "Bearer x"})
        assert r.json()["prompt"] == "PIRATE MODE" and r.json()["is_default"] is False
        r = await c.get("/admin/system-prompt", headers={"Authorization": "Bearer x"})
        assert r.json()["prompt"] == "PIRATE MODE"
        # empty resets to default
        r = await c.put("/admin/system-prompt", json={"prompt": "  "},
                        headers={"Authorization": "Bearer x"})
        assert r.json()["is_default"] is True
        r = await c.get("/admin/system-prompt", headers={"Authorization": "Bearer x"})
        assert r.json() == {"prompt": "DEFAULT PERSONA", "is_default": True,
                            "default": "DEFAULT PERSONA"}


# ---------------------------------------------------------------- feedback
async def test_feedback_requires_auth(app):
    async with await _client(app) as c:
        r = await c.post("/messages/5/feedback", json={"rating": 1})
    assert r.status_code == 401


async def test_feedback_rate_and_toggle(app):
    app.dependency_overrides[get_current_user] = _user
    async with await _client(app) as c:
        r = await c.post("/messages/5/feedback", json={"rating": 1},
                         headers={"Authorization": "Bearer x"})
        assert r.json() == {"message_id": 5, "rating": 1}
        # same rating toggles off
        r = await c.post("/messages/5/feedback", json={"rating": 1},
                         headers={"Authorization": "Bearer x"})
        assert r.json()["rating"] == 0
        # invalid rating
        r = await c.post("/messages/5/feedback", json={"rating": 2},
                         headers={"Authorization": "Bearer x"})
        assert r.status_code == 422


async def test_feedback_summary_admin_gated(app):
    app.dependency_overrides[get_current_user] = _user
    async with await _client(app) as c:
        r = await c.get("/admin/feedback/summary", headers={"Authorization": "Bearer x"})
    assert r.status_code == 403


async def test_feedback_summary_admin_ok(app):
    app.dependency_overrides[get_current_user] = _admin
    await app.state.feedback.rate(5, "7", -1)
    async with await _client(app) as c:
        r = await c.get("/admin/feedback/summary", headers={"Authorization": "Bearer x"})
    assert r.status_code == 200
    assert r.json()["down"] == 1


# ---------------------------------------------------------------- judge (admin)
async def test_judge_endpoints_admin_gated(app):
    app.dependency_overrides[get_current_user] = _user
    async with await _client(app) as c:
        assert (await c.post("/admin/eval/judge", json={},
                             headers={"Authorization": "Bearer x"})).status_code == 403
        assert (await c.get("/admin/eval/status",
                            headers={"Authorization": "Bearer x"})).status_code == 403


async def test_judge_run_and_status_admin(app):
    app.dependency_overrides[get_current_user] = _admin
    async with await _client(app) as c:
        r = await c.post("/admin/eval/judge", json={"limit": 5},
                         headers={"Authorization": "Bearer x"})
        assert r.status_code == 200 and r.json()["judged"] == 3
        s = await c.get("/admin/eval/status", headers={"Authorization": "Bearer x"})
        assert s.status_code == 200 and s.json()["avg_scores"]["answer_relevance"] == 0.9


# ---------------------------------------------------------------- golden (admin)
async def test_golden_admin_gated(app):
    app.dependency_overrides[get_current_user] = _user
    async with await _client(app) as c:
        assert (await c.get("/admin/golden",
                            headers={"Authorization": "Bearer x"})).status_code == 403
        assert (await c.post("/admin/golden", json={"query": "q"},
                             headers={"Authorization": "Bearer x"})).status_code == 403


async def test_golden_crud_and_eval(app):
    app.dependency_overrides[get_current_user] = _admin
    async with await _client(app) as c:
        # create
        r = await c.post("/admin/golden", json={
            "query": "how long for a refund?", "reference_answer": "14 days",
            "relevant_chunks": [{"doc_id": "d1", "chunk_index": 0, "relevance": 2}],
        }, headers={"Authorization": "Bearer x"})
        assert r.status_code == 200
        qid = r.json()["id"]
        assert r.json()["relevant_chunks"][0]["relevance"] == 2
        # list
        r = await c.get("/admin/golden", headers={"Authorization": "Bearer x"})
        assert len(r.json()["queries"]) == 1
        # update
        r = await c.put(f"/admin/golden/{qid}", json={"query": "q2", "relevant_chunks": []},
                        headers={"Authorization": "Bearer x"})
        assert r.json()["query"] == "q2" and r.json()["relevant_chunks"] == []
        # run eval (fake runner)
        r = await c.post("/admin/golden/eval", json={},
                         headers={"Authorization": "Bearer x"})
        assert r.status_code == 200 and r.json()["aggregate"]["correctness"] == 0.75
        # latest
        r = await c.get("/admin/golden/runs/latest", headers={"Authorization": "Bearer x"})
        assert r.status_code == 200 and r.json()["num_queries"] == 2
        # delete
        assert (await c.delete(f"/admin/golden/{qid}",
                               headers={"Authorization": "Bearer x"})).status_code == 204
        assert (await c.delete("/admin/golden/9999",
                               headers={"Authorization": "Bearer x"})).status_code == 404
