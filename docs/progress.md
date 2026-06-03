# Progress

Status snapshot. All tests green: **129 unit + 4 integration**.

## Milestones (mapped to commits)

| Commit | What landed |
| --- | --- |
| `58b8481` | Initial FastAPI chatbot + multi-provider LLM abstraction (anthropic/openai/gemini/ollama) + pytest suite. |
| `00a98d4` | OpenAI provider uses `max_completion_tokens` (GPT-5 series rejects `max_tokens`). |
| `89129d3` | Layered architecture: core worker + Redis Streams + Postgres durable + Redis hot store; HTTP/CLI gateways with correlation; Alembic `0001`. |
| `f50da01` | Dedicated host ports (Redis 6380 / Postgres 5434) to avoid collisions. |
| `62b4737` | Tier-3 per-user fact memory + token-driven tiers 1-2 (tiktoken); Alembic `0002` (`user_memory`). |
| `5bd186a` | Fix "over-retire": ignore a `retire` for a key also set in the same delta. |
| `01bc80c` | Tier-4 RAG (Qdrant + OpenAI embeddings) + extensible tool-calling framework; admin `/ingest`. |
| _(latest)_ | `web_search` tool via Brave API; `@tool(requires=...)` config-gated registration. |

## Memory tiers — all built

1. **Current context (tier-1)** — recent whole turns under `CONTEXT_WINDOW_TOKENS` (per channel).
2. **Channel summary (tier-2)** — short running summary folded from window overflow (per channel, ~150 tokens).
3. **User facts (tier-3)** — durable per-user JSON document (`user_memory`): structured facts + cross-session rolling summary, LLM-extracted at `FACT_EXTRACTION_TOKENS`.
4. **RAG (tier-4)** — curated knowledge in Qdrant, retrieved via the `search_knowledge` tool (model-decided).

Identity: tiers 1-2 keyed `platform:channel_id`; tiers 3-4 keyed `platform:user_id`.

## What runs today

- **Processes**: `interfaces/worker.py` (core consumer), `interfaces/http_app.py`
  (chat gateway, `POST /chat`), `interfaces/admin_app.py` (`POST /ingest`),
  `interfaces/cli.py` (fake adapter).
- **Stores**: Redis (streams + hot), Postgres (`sessions`/`messages`/`summaries`/`user_memory`), Qdrant (`knowledge` collection).
- **LLM**: configured for OpenAI `gpt-5.4-mini` in local `.env`.

## Test inventory

Run unit tests with `pytest -m "not integration"` (the default via `pytest.ini`),
integration with `pytest -m integration` (needs `docker compose up -d`).

| Test file | Covers |
| --- | --- |
| `test_config.py` | settings defaults / provider resolution |
| `test_factory.py`, `test_openai_provider.py` | provider factory; OpenAI `generate_reply` + `complete()`/tools |
| `test_token_counter.py`, `test_token_window.py` | tiktoken counting; whole-turn windowing |
| `test_hot_store.py`, `test_context_builder.py`, `test_summarizer.py` | Redis hot store; prompt assembly; overflow fold |
| `test_events.py`, `test_repository.py` | event serialisation round-trips; persistence repo |
| `test_user_memory_repo.py` (incl. schema), `test_facts_store.py`, `test_facts_renderer.py`, `test_facts_extractor.py` | tier-3 schema/repo/store/render/extract (incl. supersede + over-retire guard) |
| `test_tool_registry.py`, `test_tool_loop.py` | tool registry; ToolRunner loop + guards |
| `test_embeddings.py`, `test_vector_store.py`, `test_chunking.py`, `test_search_tool.py`, `test_ingest.py` | tier-4 RAG units (mocked) |
| `test_web_search.py` | Brave `web_search` tool: formatting, params, degrade, key-gated registration |
| `test_pipeline.py` | end-to-end pipeline incl. tier-2/3/4 paths + invariants |
| `test_http_chat.py` | HTTP gateway (200/502/504/422) |
| `integration/test_roundtrip.py` | real Redis+Postgres inbound→outbound |
| `integration/test_rag_roundtrip.py` | real Qdrant + OpenAI embeddings ingest→search |
| `integration/test_web_search_roundtrip.py` | real Brave API search + tool formatting (skips without key) |

Unit tests use **fakeredis**, in-memory **SQLite (StaticPool)**, and **FakeChat**
fakes — no network or Docker needed. (See [decisions.md](decisions.md) on why
SQLite/fakeredis are test-only.)

## Verified live (OpenAI gpt-5.4-mini)

- Memory carries across turns ("記住我叫小明" → later recalled).
- Facts auto-extracted into `user_memory`: `single` replace moves the old value
  to `superseded`, `multi` (e.g. languages) accumulates, plus a rolling summary.
- RAG: ingested a refund policy; the model **autonomously called
  `search_knowledge`** and answered from it; unrelated questions skip the tool.

## Known limitations / rough edges

- **Adapters**: only HTTP + CLI exist (effectively 1:1). Line/Discord not built
  yet — group multi-user behaviour is modelled but unexercised.
- **Tools**: only OpenAI implements tool-calling; other providers fall back to
  plain text. Two real tools: `search_knowledge` (RAG) and `web_search` (Brave;
  registered only when `BRAVE_API_KEY` is set).
- **RAG content**: curated uploads only (no auto-indexed conversation / distilled
  experience yet). `RAG_SCORE_THRESHOLD` defaults to 0 (uncalibrated).
- **Tuning**: `fact_system_prompt` can occasionally over-retire (mitigated by a
  code guard, but the prompt could be sharper); channel-summary length relies on
  prompt + render truncation (no per-call `max_tokens` cap).
- **Ops**: no auth/rate-limiting on gateways; ingest is unauthenticated; app
  processes aren't containerised; no CI yet.

See [roadmap.md](roadmap.md) for the planned work and where each slots in.
