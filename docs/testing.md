# Testing — how this repo does TDD & BDD

## Test taxonomy (where a new test goes)

| Layer | Where | When to write it |
| --- | --- | --- |
| **Behavior (BDD)** | `features/*.feature` + `tests/bdd/` | New user-visible feature: write the Gherkin scenario FIRST, watch it fail, then build down. Scenarios are business-readable specs — no Redis/SQL/fixture vocabulary in the .feature files. |
| **Unit / component** | `tests/test_*.py` | New module, bugfix (regression test first, always), edge cases, error paths. |
| **Integration** | `tests/integration/` (`-m integration`) | Real Redis/Postgres/Qdrant round-trips. Manual: `docker compose up -d` first. |

## The loop (red → green → refactor)

1. **Behavior change?** Add a scenario to the matching `.feature` file (or a new
   one + a tiny `scenarios()` binder in `tests/bdd/`). Run it — it must fail for
   the right reason.
2. Drop down: write the failing unit test for the piece you're about to build.
3. Implement until green. Run the full suite (`pytest` — it's ~15s).
4. Refactor with the suite green. Commit names the behavior, not the files.

For bugfixes the order is non-negotiable: failing regression test first, fix
second. (Example in history: the reranker-failure fallback in
`core/pipeline.py` — test red in `tests/test_adaptive_rag.py`, then the fix.)

## House rules

- **Never assert on `AsyncMock.call_args` for our own code.** Use a recording
  fake and assert observable behavior (what was stored, what comes back, what
  was excluded). `tests/test_vector_store.py::RecordingQdrantClient` is the
  pattern. One wire-shape assertion is allowed only where the request shape IS
  the contract (e.g. the Qdrant collection schema).
- **Assert persisted state over interactions**: db rows, hot-store contents,
  stream entries — not "method X was called".
- **Every `except` branch in production code gets a test that drives it.**
  Resilience code that's never exercised is a liability (the untested worker
  loop hid an event-loop starvation hazard for months).
- **Async fakes must actually suspend or be cheap.** A `while True` reader over
  a non-blocking fake starves the loop — see the idle pause in
  `shared/redis_client.py::read_group`.

## Fixtures & facades (what already exists — reuse, don't rebuild)

- `tests/factories.py` — `new_fake_redis()`, `new_sqlite_engine()`,
  `build_deps(settings, redis, sessionmaker, chat, **overrides)` (overrides set
  any `PipelineDeps` field: classifier/retriever/reranker/eval_logger/…).
- `tests/conftest.py` — `make_settings(**kw)`, `redis`/`sessionmaker` fixtures,
  `FakeChat` (echo), `ToolCallingFakeChat` (scripted tool calls),
  `FakeEmbedding`, `FakeVectorStore`, `FakeSparseEmbedder`.
- `tests/bdd/world.py` — `World` (drives `handle_inbound`; verbs: `user_says`,
  `ingest_document`, `wire_rag`, `expire_hot_cache`, `run_idle_sweeper`,
  `db_messages/db_summaries/db_sessions/eval_chunks`, `prompt_text`) and
  `ApiWorld` (HTTP over ASGI with a real `OutboundWaiter` + in-loop worker
  pump; verbs: `register/login/send_chat/rate_reply/get/post`).
- BDD steps live in `tests/bdd/conftest.py`; binder files just call
  `scenarios("x.feature")`.

**Why the World is sync:** pytest-bdd 8.x has no async step support, and sync
scenarios can't consume pytest-asyncio fixtures. The World owns a persistent
`asyncio.Runner` and builds its resources via `tests/factories.py` instead.

## Runbook

```bash
pytest                      # unit + BDD, no coverage (~15s)
pytest tests/bdd            # scenarios only (~2s)
pytest --cov                # with the coverage gate (pre-push; CI runs this)
pytest -m integration       # real backends (docker compose up -d first)
```

## Coverage ratchet

`.coveragerc` enforces `fail_under` in CI (`pytest --cov`). The floor only
moves up: when total coverage rises ≥1 point above the floor, bump
`fail_under` to (new coverage − 1). Never lower it; if a change would drop
below the floor, the change needs tests, not a lower floor. Omitted from
measurement: manual/interactive entrypoints (`interfaces/cli.py`,
`interfaces/judge.py`, `interfaces/discord_app.py`).

## Mutation testing (optional, manual)

Not in CI — on an asyncio-heavy suite mutmut is slow and resilience code
produces noisy surviving mutants. Before a major release it can be worth a
scoped manual run:

```bash
pip install mutmut
mutmut run --paths-to-mutate core/pipeline.py,core/tools/loop.py,core/memory/
```
