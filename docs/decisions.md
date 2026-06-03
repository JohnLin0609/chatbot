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
