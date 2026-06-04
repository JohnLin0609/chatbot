# Progress

Status snapshot. Backend tests green: **203 unit + 4 integration** (`pytest`).
Frontend: **16 tests** (`cd frontend && npm run test`).

> The chatbot is a **control console** (chat UI + admin RAG management + chunk
> visualiser + auth), built in phases — all done: **Phase 1 = backend RAG
> engine + document model**, **Phase 2 = auth + unified API**, **Phase 3 =
> frontend SPA**. See [roadmap.md](roadmap.md).

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
| _(prev)_ | `web_search` tool via Brave API; `@tool(requires=...)` config-gated registration. |
| _(prev)_ | Discord adapter (`discord.py`, mention/DM trigger, reaction status UX) + pub/sub progress channel for live tool/think status. |
| _(prev)_ | **Phase 1 RAG engine**: hybrid (dense + BM25 sparse + RRF), Adaptive-RAG classifier routing, local Qwen3 rerank, per-type chunking (slides/prose/token), `documents` registry + enable/disable (Alembic `0003`), admin doc/chunk APIs. |
| _(prev)_ | **Phase 2 auth + unified API**: JWT bearer auth, `users` table (Alembic `0004`, first-user-admin), single `interfaces/api_app.py` (`/auth/*` + `/chat` + admin-gated docs) replacing http_app + admin_app. |
| _(prev)_ | **Phase 3 frontend SPA** (`frontend/`, React + Vite + TS + Tailwind): login/register, Claude-like chat tester, admin console (upload text/pptx, document toggle, chunk inspector). Vitest suite + browser e2e. |
| _(latest)_ | Session lifecycle: 10-min hot TTL (decoupled tier-3 mirror TTL) + worker **idle-sweeper** that finalises ended sessions into tier-2 summary + tier-3 facts (Alembic `0005` `sessions.finalized_at`). |

## Memory tiers — all built

1. **Current context (tier-1)** — recent whole turns under `CONTEXT_WINDOW_TOKENS` (per channel).
2. **Channel summary (tier-2)** — short running summary folded from window overflow (per channel, ~150 tokens).
3. **User facts (tier-3)** — durable per-user JSON document (`user_memory`): structured facts + cross-session rolling summary, LLM-extracted at `FACT_EXTRACTION_TOKENS`.
4. **RAG (tier-4)** — curated knowledge in Qdrant (named **dense + BM25 sparse**
   vectors), retrieved via **Adaptive-RAG**: a front LLM classifier routes each
   query `simple` (no retrieval) / `medium` (hybrid → fused Top 3) / `complex`
   (hybrid → Qwen3 rerank → Top 3); results are injected into the prompt. Chunked
   per document type (slides/prose/token); per-doc enable/disable filters retrieval.

Identity: tiers 1-2 keyed `platform:channel_id`; tiers 3-4 keyed `platform:user_id`.

## What runs today

- **Processes**: `interfaces/worker.py` (core consumer **+ idle-session
  finalization sweeper**), `interfaces/api_app.py` (unified console API: auth +
  `/chat` + admin-gated docs/ingest, port 8753), `interfaces/cli.py` (fake
  adapter), `interfaces/discord_app.py` (Discord bot).
- **Frontend**: `frontend/` (React + Vite SPA, `npm run dev` on 5173) — consumes
  the API via JWT bearer; build to static `dist/`.
- **Stores**: Redis (streams + hot), Postgres (`sessions`/`messages`/`summaries`/`user_memory`/`documents`/`users`), Qdrant (`knowledge` collection — named dense + BM25 sparse vectors).
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
| `test_embeddings.py`, `test_vector_store.py`, `test_chunking.py`, `test_ingest.py` | RAG units (embeddings; named-vector + hybrid store; token chunking; ingest) |
| `test_chunkers.py`, `test_pptx.py`, `test_sparse.py` | per-type chunking (slides/prose/token), pptx parse, jieba BM25 tokenisation |
| `test_documents.py` | DocumentStore CRUD + enable/disable |
| `test_classifier.py`, `test_retriever.py`, `test_adaptive_rag.py`, `test_reranker.py` | Adaptive-RAG: classifier tiers, hybrid retrieve, routing (simple/medium/complex), rerank ordering + gate |
| `test_auth_security.py`, `test_user_store.py` | bcrypt hash/verify; JWT encode/decode; first-user-admin, duplicate, authenticate |
| `test_api_auth.py`, `test_api_chat.py`, `test_api_admin.py` | API: register/login/me; `/chat` 401-vs-authed + identity flow; admin 403-vs-200 (httpx ASGITransport + dep overrides) |
| `test_web_search.py` | Brave `web_search` tool: formatting, params, degrade, key-gated registration |
| `test_discord_adapter.py` | Discord pure helpers: trigger matrix, mention strip, reaction reducer, chunking, event mapping |
| `test_tool_loop.py` (progress) | worker emits `thinking`/`tool_start`/`tool_end` progress around the tool loop |
| `test_pipeline.py` | end-to-end pipeline incl. tier-2/3/4 paths + Adaptive-RAG injection + invariants |
| `test_finalizer.py` | idle-session finalization: tier-2 fold, tier-3 force-extract, finalized_at, sweep selection + re-entrancy |
| `integration/test_roundtrip.py` | real Redis+Postgres inbound→outbound |
| `integration/test_rag_roundtrip.py` | real Qdrant + OpenAI: ingest → dense + **hybrid** (BM25/RRF) search |
| `integration/test_web_search_roundtrip.py` | real Brave API search + tool formatting (skips without key) |

Unit tests use **fakeredis**, in-memory **SQLite (StaticPool)**, and **FakeChat**
fakes — no network or Docker needed. (See [decisions.md](decisions.md) on why
SQLite/fakeredis are test-only.)

**Frontend** (`frontend/`, Vitest + React Testing Library, 16 tests): API client
(Bearer / 401), auth context, route guards (protected + admin), ChunkInspector
& MessageBubble render, conversation storage. Plus a manual **browser e2e**
(register→admin→upload→inspect chunks→RAG chat) verified with Playwright.

## Verified live (OpenAI gpt-5.4-mini)

- Memory carries across turns ("記住我叫小明" → later recalled).
- Facts auto-extracted into `user_memory`: `single` replace moves the old value
  to `superseded`, `multi` (e.g. languages) accumulates, plus a rolling summary.
- RAG (Phase 1, component-verified live): hybrid ingest→search over real Qdrant
  (dense + BM25/RRF); Qwen3-Reranker-0.6B loads and ranks refund docs above an
  unrelated one. Full classifier-routed pipeline end-to-end is pending a live run.

## Known limitations / rough edges

- **Adapters**: HTTP, CLI, and Discord exist. Line not built yet. Discord group
  multi-user behaviour is modelled and now exercisable, but not load-tested.
  Discord's live end-to-end path (gateway/reactions) is manually verified, not in
  the automated suite (discord.py needs a real gateway + token).
- **Tools**: only OpenAI implements tool-calling; other providers fall back to
  plain text. One real tool now: `web_search` (Brave; registered only when
  `BRAVE_API_KEY` is set). Knowledge RAG is no longer a tool — it's
  classifier-routed in the pipeline.
- **RAG engine**: heavy deps (fastembed / spaCy / torch+transformers) are optional
  and degrade (dense-only / token chunks / no-rerank). Classifier adds one LLM
  call per message. Reranker is CPU-slow without a GPU. `xx_sent_ud_sm` zh/en
  sentence boundaries are decent but not perfect. The named-vector collection is a
  **breaking schema change** — recreate + re-ingest. Auth + frontend are Phase 2/3.
- **RAG content**: curated uploads only (no auto-indexed conversation / distilled
  experience yet). `RAG_SCORE_THRESHOLD` defaults to 0 (uncalibrated).
- **Tuning**: `fact_system_prompt` can occasionally over-retire (mitigated by a
  code guard, but the prompt could be sharper); channel-summary length relies on
  prompt + render truncation (no per-call `max_tokens` cap).
- **Auth**: JWT bearer auth now gates the API (`/chat` requires a user; docs/ingest
  require admin). Still missing: refresh tokens, rate limiting, password reset, and
  the frontend (Phase 3). Registration is open (first user = admin); lock via
  `AUTH_OPEN_REGISTRATION=false`.
- **Ops**: app processes aren't containerised; no CI yet.

See [roadmap.md](roadmap.md) for the planned work and where each slots in.
