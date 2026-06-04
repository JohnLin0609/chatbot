# Design decisions

The "why" behind the architecture, captured so future work doesn't relitigate
settled choices. Each entry: the decision, and the reasoning.

## Topology & transport

- **Core service + separate adapter processes** (not a monolith). The core is
  platform-neutral; adapters are independent processes. Lets them scale/deploy
  independently and keeps platform specifics out of the core.
- **Async + post-hoc push.** An adapter acks the platform immediately, the core
  processes, then the reply is pushed back. Decouples the (slow) LLM call from
  the platform's response window.
- **Redis Streams + consumer groups.** Inbound stream consumed by `core-workers`
  (horizontal scale + `XACK` + `XAUTOCLAIM` for crashed workers); outbound
  consumed by per-gateway groups (`http-gateway`/`cli-gateway`, later one per
  adapter). Correlation via a `correlation_id` + `OutboundWaiter` gives the HTTP
  gateway a synchronous feel over async streams.

## Memory

- **Redis hot + Postgres durable.** Redis holds recent turns + summaries + a
  per-user memory mirror (fast path, TTL'd); Postgres is the source of truth.
  Cold/expired hot store is rebuilt from Postgres.
- **Two identities.** `session_id = platform:channel_id` scopes the conversation
  window + channel summary; `user_key = platform:user_id` scopes durable facts +
  a cross-session personal summary. A group channel shares the conversation
  memory but each speaker keeps their own facts.
- **Token water-levels, not turn counts.** Sizing uses tiktoken. `CONTEXT_WINDOW_TOKENS`
  defines tier-1; `FACT_EXTRACTION_TOKENS` triggers tier-3. Whole-turn boundaries
  only (never split a turn). Reason: turns vary wildly in length; tokens are what
  actually cost/fit.
- **Two coexisting summaries.** A short per-channel summary (tier-2, ~150 tokens)
  *and* a per-user cross-session rolling summary (inside the tier-3 doc). They
  answer different questions ("what's this channel about" vs "who is this user").
- **Summary on overflow.** Turns that overflow the window are folded into the
  channel summary immediately (closest to the sliding-window intuition), trading
  more frequent summary calls for freshness.
- **The mid-band invariant.** When the window shrinks, evicted turns are folded
  into the summary but kept in Postgres `messages` until tier-3 consumes them.
  The per-user `last_extracted_message_id` cursor advances *only* after a
  successful extraction — so the band "out of window, summarised, not yet
  extracted" is never lost.

## Facts (tier-3)

- **Per-user JSON document** (`user_memory.document`, JSONB): `rolling_summary`
  + `facts{key: {value, cardinality, confidence, source, timestamps}}` +
  `superseded[]` + `schema_version`. LLM-extracted as a delta, merged in code.
- **Merge rules.** `single` cardinality → new value replaces, old → `superseded`
  (created_at preserved). `multi` → values accumulate (dedup). `retire` → moves a
  fact to `superseded`. Confidence defaults to 0.5.
- **Render-slimming for injection.** Facts are rendered to `key: value` (metadata
  stripped), ranked by `confidence × recency`, filled up to
  `PERSONAL_MEMORY_TOKEN_CAP`; `last_used_at` bumped for injected facts. The token
  cap applies to the *rendered* text, not the stored JSON.
- **Over-retire guard.** If the LLM returns a contradictory delta (same key in
  both `facts` and `retire`), the new value wins — the retire is skipped. This is
  order-independent and keeps `created_at`/`last_used_at` (vs swapping loop order,
  which would lose metadata). The prompt was also tightened. (Symptom seen live:
  an "I changed jobs" turn made the model both set and retire `profession`,
  netting to data loss.)

## RAG & tools (tier-4)

- **Curated uploads first, not raw conversation.** Embedding every turn pollutes
  retrieval and duplicates tiers 1-3. "Experience" has no clean rule-based
  definition, so it's deferred to LLM-distilled case cards later. Curated docs are
  well-defined and immediately useful. The Qdrant `source` field makes the auto
  path a drop-in (`source="distilled_experience"`).
- **Qdrant** (dedicated vector DB) over pgvector — chosen for payload filtering
  and fit with the compose pattern.
- **OpenAI embeddings, fixed per collection.** The embedding model must be
  constant for a collection (dimension/consistency), so it's its own setting
  (`EMBEDDING_*`), independent of the switchable chat `PROVIDER`.
- **Retrieval is a tool, not a prefetch.** The model decides when to call
  `search_knowledge`. Tier 1-3 injection stays hardcoded.
- **Low-impact tool integration.** `ChatService.generate_reply` (used by tier-2/3)
  is left untouched; tool-calling goes through a new `complete(messages, tools)`.
  `ToolRunner` falls back to a single completion when tools are off/unsupported,
  so existing behaviour and tests are unchanged. OpenAI's `complete` keeps the
  assistant message verbatim (`model_dump`) so the tool-call message stack stays
  valid (mismatched `tool_call_id`s would 400).

## Adapters & live progress

- **Discord = persistent gateway bot, per-message await.** `interfaces/discord_app.py`
  reuses `OutboundWaiter` (the HTTP/CLI correlation helper): on a message it
  registers a `correlation_id`, publishes inbound, and awaits the matching
  outbound while showing a typing indicator. Simple, ordered, good UX. Trade-off:
  a reply in flight during a bot restart is lost (acceptable for chat). It runs as
  a single instance with its own `discord-gateway` consumer group.
- **Trigger: @mention in guilds, every DM.** Keeps the bot quiet in busy servers
  and requires the privileged **Message Content Intent**. Bots/self are ignored
  (loop prevention). Optional guild allowlist (`DISCORD_ALLOWED_GUILDS`).
- **Progress over a separate pub/sub channel, not the outbound stream.** Tool
  calls happen inside the worker, so the adapter can't know when (e.g.)
  `web_search` runs. The worker broadcasts `thinking`/`tool_start`/`tool_end`
  `ProgressEvent`s on a Redis **pub/sub** channel (`PROGRESS_CHANNEL`).
  Pub/sub (not a durable stream) is deliberate: progress is *ephemeral and
  best-effort* — a dropped message just means a momentarily stale indicator, while
  the authoritative reply still arrives on the durable outbound stream. The
  emitter is optional/no-op everywhere except the live worker, so the non-Discord
  paths and unit tests are unchanged (same low-impact pattern as the web_search
  `ToolContext` field).
- **Reaction status UX = single self-cleaning phase emoji.** The bot reacts to the
  user's own message with exactly one current-phase emoji that advances
  (👀 received → 🧠 thinking → per-tool emoji like 🌐 `web_search` → ✅ done / ❌
  error). Each transition removes the previous reaction and adds the new one, so a
  finished message shows only ✅. Per-tool emojis come from a map, so a new tool
  gets its own reaction (default 🛠️) with no adapter change.

## RAG engine — hybrid + Adaptive-RAG + per-type chunking (Phase 1 of control console)

The chatbot is becoming a **control console** (chat UI + admin RAG management +
chunk visualiser + auth), built in phases: **1 = backend RAG engine + document
model** (done), 2 = auth/API, 3 = frontend. The Phase-1 engine replaced the old
token-chunked, dense-only, tool-triggered RAG:

- **Hybrid retrieval (dense + BM25 sparse, RRF).** Each chunk carries a dense
  vector (OpenAI) and a BM25 **sparse** vector (fastembed) in a Qdrant
  **named-vector** collection; queries fuse both server-side via the Query API
  (`Prefetch` × 2 + `FusionQuery(RRF)`). The sparse vector config **must** set
  `Modifier.IDF` — fastembed emits term frequencies only; Qdrant computes IDF
  from collection stats at query time. **Chinese is segmented with jieba** before
  BM25 at both ingest and query (shared `tokenize_for_bm25`), else CJK BM25 is
  dead weight. Degrades to dense-only if fastembed is absent.
- **Adaptive-RAG routing (front LLM classifier).** A small classifier call labels
  each query `simple|medium|complex`: simple → answer directly (no retrieval);
  medium → hybrid retrieve, inject fused **Top 3**; complex → retrieve a larger
  candidate set → **rerank** → Top 3. Chosen over a tool-parameter so routing is
  explicit/controllable. Knowledge RAG therefore moved from a model-called tool
  to a **classifier-routed pre-fetch** injected into the prompt; the
  `search_knowledge` tool was **removed**. `web_search` stays a model-called tool.
  Classifier failures default to `medium` (retrieve, don't drop knowledge).
- **Local Qwen3-Reranker-0.6B (complex tier only).** Small + multilingual (good
  Chinese), so it fits even though it adds torch/transformers. Lazy-loaded,
  inference in `asyncio.to_thread`; if unavailable, complex degrades to the fused
  Top 3 (same as medium). Reranking only the complex tier bounds its cost.
- **Per-type chunking.** A strategy registry keyed by `doc_type`: **slides**
  (`.pptx` → python-pptx, one chunk per slide, split if over budget), **prose**
  (spaCy `xx_sent_ud_sm` multilingual sentence segmentation, greedily packed to
  the token budget with N-sentence overlap to preserve semantic boundaries),
  **token** (fixed windows; fallback when spaCy is unavailable).
- **Document registry + enable/disable.** A Postgres `documents` table is the
  source of truth for the doc list/UI; chunks live in Qdrant. Toggling `enabled`
  updates Postgres **and** mirrors to the Qdrant payload, so retrieval filters
  `source="curated" AND enabled=true`. A chunk-inspection API (`scroll_doc`) feeds
  the future visualiser.
- **Heavy ML deps are optional + gated.** fastembed / spaCy / torch+transformers
  each degrade gracefully (dense-only / token chunks / no-rerank), so the unit
  suite and CI run without them.

## Auth & unified API (Phase 2 of control console)

- **JWT bearer, access-token only.** Stateless (no session store), fits the
  existing stateless API and is simplest for the SPA. Refresh tokens / rotation
  deferred — the trade-off is that a token can't be revoked before it expires.
- **One unified API app** (`interfaces/api_app.py`) replacing the separate chat
  (`http_app`) and admin (`admin_app`) apps. The SPA gets one origin + one token;
  admin routes are gated by a `require_admin` dependency. Built via a
  `build_app(...)` factory so tests inject fakes and bypass lifespan (httpx
  `ASGITransport` + `dependency_overrides`).
- **Open self-registration; first account = admin.** Zero-config bootstrap (no
  seed/env needed) for a personal console; lockable later via
  `AUTH_OPEN_REGISTRATION=false`. The unique-email constraint guards duplicates.
- **Authenticated identity drives memory.** `POST /chat` sets the inbound
  `user_id` to the account id (`platform="web"`), so tier-3 personal memory keys
  to the real user; `channel_id = "<user_id>:<conversation_id>"` scopes tier-1/2
  per chat thread.
- **Adapters stay unauthenticated by design.** CLI/Discord are trusted
  server-side processes that publish to the Redis streams directly; auth is an
  HTTP-edge concern, so only the API enforces it. bcrypt for passwords, pyjwt for
  tokens — small, standard, no heavyweight framework.

## Infrastructure

- **Dedicated host ports** (Redis 6380, Postgres 5434) because the dev machine
  already had services on 6379/5432/5433. Qdrant uses standard 6333 (was free).
- **SQLite + fakeredis are test-only.** Unit tests use in-memory SQLite
  (`StaticPool` for a shared connection) and fakeredis so they run in
  milliseconds without Docker. Runtime is always Postgres + real Redis. `aiosqlite`
  is a dev-only dependency; `models.py` uses `BigIntPK`/`JsonDoc` variants so the
  ORM works on both.

## Notable runtime gotchas (already handled)

- OpenAI GPT-5 series rejects `max_tokens` → use `max_completion_tokens`.
- `XREADGROUP BLOCK` surfaces an idle timeout as an exception → treated as "no
  messages" so the worker loop is stable.
- qdrant-client ≥1.18 removed `search` → use `query_points` (and
  `check_compatibility=False` for minor client/server skew).
