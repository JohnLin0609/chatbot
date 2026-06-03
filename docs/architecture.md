# Architecture

## Layers

Two logical layers in separate processes:

- **Core** (`core/`, run via `interfaces/worker.py`) — platform-agnostic. Owns
  conversation behaviour: session management, memory, summarisation, and the LLM
  call. Knows nothing about Line/Discord/HTTP.
- **Adapters** (`interfaces/`) — front-end connectors. HTTP gateway and CLI
  exist today; Line and Discord come later. Each adapter normalises a platform
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
  `{role,content,ts,user_id}`) and the channel summary (STRING) per session,
  plus a per-user memory mirror, TTL-refreshed on write.
- **PostgreSQL** (`core/persistence/`): durable source of truth — `sessions`,
  `messages`, `summaries`, and `user_memory` (per-user JSONB document + an
  extraction cursor). On a cold/expired hot store the pipeline backfills from
  Postgres.

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
The same service is reused for summarisation.

## Deferred (next phases)

- Line adapter (webhook FastAPI → inbound; outbound via reply/push API).
- Discord adapter (discord.py gateway bot → inbound; outbound to channel).
- Dedupe hardening, streaming replies, auth, rate limiting, containerising the
  core into compose.
```
