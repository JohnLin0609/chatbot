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

- **Redis hot store** (`core/memory/hot_store.py`): recent turns (LIST) and the
  running summary (STRING) per session, TTL-refreshed on write. Fast path for
  building context.
- **PostgreSQL** (`core/persistence/`): durable full history — `sessions`,
  `messages`, `summaries`. On a cold/expired hot store the pipeline backfills
  recent context from Postgres.

## Context strategy: summary + recent

Each turn the pipeline feeds the LLM: system prompt + running summary + the last
`RECENT_TURNS` turns + the current message (`core/memory/context_builder.py`).
When unsummarised turns reach `SUMMARY_TRIGGER_TURNS`, the summariser
(`core/summary/summarizer.py`) folds the older turns into the running summary
with one LLM call, keeps the last `RECENT_TURNS`, and persists the new summary.

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
