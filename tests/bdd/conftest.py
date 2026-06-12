"""Shared World fixtures + step definitions for all BDD scenarios.

Steps are sync (pytest-bdd has no async support) and translate business
phrases into World/ApiWorld verbs. Keep Gherkin free of infrastructure
vocabulary — Redis/SQL/fixture talk belongs here, not in the .feature files.
"""

import pytest
from pytest_bdd import given, parsers, then, when

from core.rag.classifier import COMPLEX, SIMPLE
from tests.bdd.world import ApiWorld, World


@pytest.fixture
def world():
    w = World()
    yield w
    w.close()


@pytest.fixture
def api():
    w = ApiWorld()
    yield w
    w.close()


# ================================================== conversation / pipeline
@given("a fresh conversation")
def fresh_conversation(world):
    return world


@given(parsers.parse('the knowledge base contains a document "{title}" '
                     'with content "{content}"'))
def kb_document(world, title, content):
    world.ingest_document(title, content)


@given("the router classifies messages as simple")
def router_simple(world):
    world.deps.classifier.tier = SIMPLE


@given("the router classifies messages as complex")
def router_complex(world):
    world.deps.classifier.tier = COMPLEX


@given("the knowledge base is unavailable")
def kb_down(world):
    world.wire_rag(fail=True)


@given("sessions are finalized as soon as they go idle")
def finalize_immediately(world):
    world.settings.session_finalize_idle_seconds = 0


@when(parsers.parse('the user says "{text}"'))
def user_says(world, text):
    world.user_says(text)


@when("the conversation cache expires")
def cache_expires(world):
    world.expire_hot_cache()


@when("the idle sweeper runs")
def sweeper_runs(world):
    world.swept = world.run_idle_sweeper()


@then(parsers.parse('the reply contains "{fragment}"'))
def reply_contains(world, fragment):
    assert fragment in world.last_reply


@then(parsers.parse('the prompt shown to the model includes "{fragment}"'))
def prompt_includes(world, fragment):
    assert fragment in world.prompt_text()


@then(parsers.parse('the prompt cites "{label}"'))
def prompt_cites(world, label):
    assert f"({label})" in world.prompt_text()


@then("the reply is produced without consulting the knowledge base")
def reply_without_kb(world):
    assert world.last_reply
    assert world.retriever.called is False


@then("the knowledge was reranked")
def knowledge_reranked(world):
    assert world.reranker.called is True


@then("the assistant still replies")
def still_replies(world):
    assert world.last_outbound.status == "ok"
    assert world.last_reply


@then("an evaluation trace records the retrieved chunk")
def eval_trace_has_chunk(world):
    chunks = world.eval_chunks()
    assert chunks and any(c.included for c in chunks)


@then("the session is marked finalized")
def session_finalized(world):
    sessions = world.db_sessions()
    assert sessions and all(s.finalized_at is not None for s in sessions)


@then("a durable channel summary exists")
def summary_exists(world):
    assert world.db_summaries()


# ============================================================ HTTP / account
@when(parsers.parse('a visitor registers as "{email}"'))
def visitor_registers(api, email):
    api.register(email)


@when(parsers.parse('another visitor registers as "{email}"'))
def another_visitor_registers(api, email):
    api.token = None
    api.register(email)


@when("a visitor sends a chat message without logging in")
def chat_without_login(api):
    api.token = None
    api.send_chat("hello?")


@given(parsers.parse("auth attempts are limited to {n:d} per minute"))
def auth_limit(api, n):
    api.settings.rate_limit_auth_per_minute = n


@when(parsers.parse("a visitor makes {n:d} login attempts"))
def login_attempts(api, n):
    for _ in range(n):
        api.login("ghost@example.com", "wrong-password")


@when(parsers.parse('they send the chat message "{message}"'))
def send_chat(api, message):
    api.send_chat(message)


@when("they rate the reply thumbs-down")
def rate_down(api):
    api.rate_reply(-1)


@then("they can fetch their own profile")
def can_fetch_profile(api):
    r = api.get("/auth/me")
    assert r.status_code == 200 and r.json()["email"]


@then("the second registration is rejected")
def second_registration_rejected(api):
    assert api.last_response.status_code == 409


@then("the request is rejected as unauthorized")
def rejected_unauthorized(api):
    assert api.last_response.status_code == 401


@then("the last attempt is rejected for too many requests")
def rejected_too_many(api):
    assert api.last_response.status_code == 429


@then(parsers.parse('they receive an assistant reply mentioning "{fragment}"'))
def assistant_reply_mentions(api, fragment):
    assert api.last_response.status_code == 200
    assert fragment in api.last_response.json()["reply"]


@then("the feedback summary shows 1 negative rating")
def feedback_summary_down(api):
    r = api.get("/admin/feedback/summary")
    assert r.status_code == 200
    assert r.json()["down"] == 1
