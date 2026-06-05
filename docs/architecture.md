# Architecture

## Layers

Two logical layers in separate processes:

- **Core** (`core/`, run via `interfaces/worker.py`) — platform-agnostic. Owns
  conversation behaviour: session management, memory, summarisation, and the LLM
  call. Knows nothing about Line/Discord/HTTP.
- **Adapters** (`interfaces/`) — front-end connectors. HTTP gateway, CLI, and
  Discord exist today; Line comes later. Each adapter normalises a platform
  message into an `InboundEvent` and sends platform replies from `OutboundEvent`s.

They never call each other directly. They exchange events over **Redis
Streams**, so adapters and core scale and deploy independently.

## Message flow (async + post-hoc push)

```
adapter ──InboundEvent──▶ chat:inbound (stream)
                              │  XREADGROUP (group: core-workers)
                              ▼
                         core worker ──▶ pipeline ──▶ LLM
                              │
   adapter ◀─OutboundEvent── chat:outbound (stream)
        (group: http-gateway / cli-gateway / line / discord)
```

1. An adapter acks the platform immediately and `XADD`s an `InboundEvent` to
   `chat:inbound`.
2. A core worker consumes it (consumer group `core-workers` → horizontal scale,
   `XACK`, `XAUTOCLAIM` for crashed workers), runs the pipeline, and `XADD`s an
   `OutboundEvent` to `chat:outbound`.
3. The adapter consumes the outbound event (its own consumer group) and sends
   the reply to the platform.

The core passes `platform`, `channel_id`, `session_id`, `correlation_id`, and
`reply_token` through verbatim — it does not interpret them. This keeps the core
platform-neutral.

## Correlation (request/response over async streams)

The HTTP and CLI gateways need a synchronous-feeling reply over the async
streams. Each request gets a unique `correlation_id`. `OutboundWaiter`
(`interfaces/correlation.py`) runs one background reader over `chat:outbound`
and resolves a per-request `asyncio.Future` when an outbound event with the
matching `correlation_id` arrives. A timeout (`REPLY_TIMEOUT_SECONDS`) yields
HTTP 504; an outbound `status="error"` yields HTTP 502.

For a real adapter (e.g. Line), `correlation_id` can carry the platform message
id instead — the mechanism is identical.

## Session identity

`session_id = platform:channel_id`. Memory is shared per channel/conversation
(a Discord channel or Line group is one memory thread). The adapter is
responsible for normalising platform ids into this key.

## Memory: hot + durable

- **Redis hot store** (`core/memory/hot_store.py`): recent turns (LIST, each
  `{role,content,ts,user_id}`) and the channel summary (STRING) per session, with
  a **10-minute idle TTL** refreshed on write. The per-user memory mirror has its
  own longer TTL (`user_memory_ttl_seconds`), decoupled from the session cache.
- **PostgreSQL** (`core/persistence/`): durable source of truth — `sessions`,
  `messages`, `summaries`, and `user_memory` (per-user JSONB document + an
  extraction cursor). On a cold/expired hot store the pipeline backfills from
  Postgres.

### Session lifecycle (idle finalization)

A session's hot cache expires after 10 min idle (= the user left). A periodic
**sweeper in the worker** (`core/session/finalizer.py`) then folds each ended
session into durable memory — the un-summarised tail → tier-2 channel summary,
and a **forced** tier-3 per-user fact extraction (bypassing the token threshold,
which short chats never reach). It's keyed on `sessions.last_active_at` +
`finalized_at`, and re-entrant via the tier-2/tier-3 cursors, so a resumed
session is re-finalised processing only new messages. Postgres stays
authoritative; raw `messages` are never deleted.

## Memory tiers (token-driven)

Sizing is by tiktoken tokens (`core/tokens/counter.py`), not turn counts. Two
configurable water-levels drive everything:

1. **Current context (tier-1)** — the most recent whole turns that fit under
   `CONTEXT_WINDOW_TOKENS` (`core/memory/token_window.py`, never splits a turn).
2. **Channel summary (tier-2, per channel)** — when turns overflow the window
   they are folded into a short (~`CHANNEL_SUMMARY_TOKEN_CAP`) running summary
   (`core/summary/summarizer.py::fold_overflow`).
3. **User facts (tier-3, per user)** — a durable per-user document
   (`core/facts/`): `rolling_summary` + structured `facts` (each with
   cardinality/confidence/timestamps) + `superseded`. When a user's
   un-extracted messages reach `FACT_EXTRACTION_TOKENS`, a separate LLM call
   (`FactExtractor`) updates the document; `single` facts replace (old value →
   `superseded`), `multi` facts accumulate, `retire` removes.

**Identity**: tier-1/2 are keyed `platform:channel_id`; tier-3 is keyed
`platform:user_id`. The pipeline injects the channel summary plus the *current
speaker's* personal memory.

**Injection slimming** (`core/facts/renderer.py`): facts are rendered to
`key: value` (metadata dropped) and ranked by confidence × recency, filled up to
`PERSONAL_MEMORY_TOKEN_CAP`; `last_used_at` is bumped for injected facts.

**Invariant**: turns evicted from the window are folded into the channel summary
but kept in Postgres `messages` until tier-3 consumes them — the per-user
`last_extracted_message_id` cursor advances only after a successful extraction,
so the mid-band (out of window, summarised, not yet extracted) is never lost.

## Pipeline (one turn)

`core/pipeline.handle_inbound` (`core/pipeline.py`):

1. `ensure_session` (upsert, bump `last_active_at`).
2. Load hot store; backfill from Postgres on cold miss.
3. Build context → call LLM (`ChatServiceError` → error outbound, nothing
   persisted).
4. Append the turn to hot store + Postgres (user & assistant rows, one
   transaction).
5. `maybe_summarize`; persist any new summary.
6. Emit `OutboundEvent` with routing/correlation passed through.

## LLM providers

`core/llm/` keeps the switchable provider abstraction
(`ChatService` + per-provider implementations + `build_chat_service`). The
interface takes a prepared message list so the core controls context assembly.
`generate_reply` is the plain-text path (tier-2/3 use it); `complete(messages,
tools=None)` is the tool-capable path. OpenAI implements tool-calling
(`supports_tools=True`); other providers inherit a default that ignores tools
and returns text, so they degrade gracefully.

## Tool-calling loop

The main reply runs through a **tool-calling loop** (`core/tools/loop.py`
`ToolRunner`). The model may call tools mid-generation; `ToolRunner` executes
the handler, stacks the result back as a `role=tool` message, and re-calls until
the model returns plain text (bounded by `TOOL_MAX_ITERATIONS`). When tools are
disabled or unsupported, it falls back to a single completion — so tier-1/2/3
behaviour is unchanged. The live tool is **`web_search`** (Brave,
`core/web/search_tool.py`), registered only when `BRAVE_API_KEY` is set.

Tools are extensible: a new tool is one `@tool(...)`-decorated async handler
(`core/tools/registry.py`); `register_default_tools` wires them into a
`ToolRegistry`, optionally gated by a `requires(settings)` predicate. Handlers
receive a `ToolContext` (settings + embedding/vector store + web-search service +
session/user ids + progress emitter).

## Tier-4: Adaptive-RAG (hybrid + rerank)

Knowledge retrieval is **not** a tool — it is classifier-routed in the pipeline.
For each message a small **classifier** (`core/rag/classifier.py`) labels the
query `simple|medium|complex`: simple → no retrieval; medium → hybrid retrieve →
fused **Top 3**; complex → hybrid retrieve a larger candidate set → **rerank**
(local Qwen3-Reranker-0.6B, `core/rag/reranker.py`) → Top 3. The chosen chunks are
injected into the prompt (`core/memory/context_builder.py`), then the tool loop
runs.

Retrieval (`core/rag/retriever.py`) is **hybrid**: each chunk has a dense vector
(OpenAI `text-embedding-3-small`) and a BM25 **sparse** vector (fastembed,
`core/rag/sparse.py`, with jieba CJK segmentation) in a Qdrant **named-vector**
collection (sparse config uses `Modifier.IDF`); the Query API fuses both with
**RRF** (`core/rag/vector_store.py`). Filtered to `source="curated"` and
`enabled=true`.

Curated documents are ingested via the unified API (`interfaces/api_app.py`, admin-only):
`POST /ingest` (text) or `POST /ingest/pptx` (slides). Chunking is **per
document type** (`core/rag/chunkers.py`): slides (one chunk per slide), prose
(spaCy sentence-grouping with overlap), token (fixed windows). A Postgres
`documents` registry (`core/documents/store.py`) tracks each doc and its
`enabled` flag (mirrored to the Qdrant payload); `GET /documents/{id}/chunks`
feeds the future chunk visualiser. The payload carries `source`/`user_key`/
`channel_id` so distilled experiences and per-user conversation RAG can be added
later without schema changes.

## Auth & the unified API (Phase 2)

`interfaces/api_app.py` is one JWT-authenticated FastAPI app (replacing the old
separate chat + admin apps) — the surface the Phase-3 SPA drives:

- `POST /auth/register` (first account → `admin`, rest → `user`), `POST /auth/login`
  → a bearer **access token** (pyjwt, HS256); `GET /auth/me`.
- `POST /chat` requires a user; the authenticated id becomes the inbound
  `user_id` (`platform="web"`), so tier-3 memory ties to the account. The response
  carries `reply_message_id` (the persisted assistant message) so it can be rated.
- `DELETE /sessions/{conversation_id}` (any user) cascade-deletes the caller's own
  session + messages + summaries + feedback (ownership is structural via the
  `web:<userId>:<conv>` key).
- `POST /messages/{id}/feedback` (any user) records a toggle/cancelable 👍/👎.
- `/documents*`, `/ingest*`, `/admin/system-prompt` (GET/PUT global persona), and
  `/admin/feedback/summary` require `admin` (`core/auth/deps.require_admin`).

Passwords are bcrypt-hashed (`core/auth/security.py`); accounts live in the
Postgres `users` table (`core/auth/store.py`). The CLI/Discord adapters are
**unauthenticated by design** — they're trusted server-side processes that
publish to the streams directly; only the HTTP API enforces auth.

## Frontend

The **Phase-3 SPA** (`frontend/`, React + Vite + TS + Tailwind) consumes this API
over JWT bearer: login/register, a chat tester (per-account conversation list in
localStorage, capped at 20 with oldest-eviction; per-reply 👍/👎), and an admin
console (upload text/`.pptx`, document enable/disable, chunk inspector, a global
**System Prompt** editor, and a **feedback summary**). Dev-served by Vite; in
Docker it's built to static `dist/` and served by nginx, which reverse-proxies the
API under `/api/` (single origin, no CORS, no SPA-vs-API path collisions).

## Eval logging (capture layer)

Every main-reply turn is captured for offline analysis (RAG retrieval metrics +
generation metrics, future LLM-as-judge). Writes are **best-effort and async**
(fire-and-forget after the turn commits) so they never block or break a reply;
toggled by `eval_logging_enabled`.

- `core/eval/instrument.py` `InstrumentedChatService` wraps the chat service per
  consumer (`main_reply`/`classifier`/`summarizer`/`fact_extract`) and records a
  lightweight **`llm_calls`** row per call (model, provider, tiktoken-estimated
  tokens, latency, ok/error) — unified cost/telemetry across every LLM call.
- `core/pipeline.py` `_retrieve_knowledge` now returns a `RetrievalTrace` (the
  classified tier + every candidate with `(doc_id, chunk_index)`/point_id, fused
  RRF score + rank, rerank score, and whether it entered the injected top-k).
  `handle_inbound` times retrieval vs generation and fires
  `EvalLogger.log_trace` (`core/eval/logger.py`), writing an **`eval_traces`** row
  (full assembled `messages`, system prompt, knowledge block, reply,
  `reply_message_id`, token/latency split) + child **`eval_retrieved_chunks`** rows.
- **`eval_golden_queries`** / **`eval_golden_relevant_chunks`** are reserved
  (created, unpopulated) for a future golden set — true Recall@k / Correctness need
  ground-truth relevance/answers that a judge over only-retrieved chunks can't
  provide. Reference-free metrics (Faithfulness, Answer Relevance, Context
  Utilization, judge-labeled Precision@k/MRR/NDCG over the retrieved set) run on
  the captured traces alone. Token usage is **tiktoken-estimated** (providers drop
  real usage today); dense/sparse scores aren't separable (RRF fuses server-side),
  so the **fused** score+rank is logged.

### LLM-as-judge (Phase B)

A reference-free judge scores the captured traces offline (never in the reply
path). `core/eval/judge.py` `Judge` makes two LLM calls per trace: a **generation**
call scoring `faithfulness` / `answer_relevance` / `context_utilization` (0–1, with
reasoning; for a no-context/simple turn only `answer_relevance` applies, the others
are stored null), and a **chunk-relevance** call labeling each retrieved chunk 0–1
(this unlocks Precision@k/MRR/NDCG/Hit Rate over the retrieved set). Results land in
tall, re-judgeable tables **`eval_judgements`** (row per trace+metric) and
**`eval_chunk_labels`** (row per chunk), tagged with `judge_model` + `judge_run_id`.
The judge model is configurable (`JUDGE_PROVIDER`/`JUDGE_MODEL`, falls back to the
main model) and its calls are themselves logged as `llm_calls` (`call_type=judge`).
`core/eval/runner.py` `JudgeRunner` batch-scores **un-judged** traces (NOT EXISTS),
committing per trace; driven by the CLI `python -m interfaces.judge [--all|--limit N]`
or the admin API `POST /admin/eval/judge` + `GET /admin/eval/status`.

## Deferred (next phases)

- Embedding 2D-projection chunk visualiser; streaming chat.
- Line adapter (webhook FastAPI → inbound; outbound via reply/push API).
  (Discord — discord.py gateway bot with reaction status UX — is **built**.)
- Auto-distilled conversation experiences; per-user conversation RAG;
  `get_member_memory` group tool; multi-provider tool support.
- Refresh tokens, rate limiting, password reset; dedupe hardening; streaming.
```
