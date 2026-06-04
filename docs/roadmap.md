# Roadmap

Planned-but-unbuilt work, with the extension point that already exists for each
(most of the scaffolding is in place by design).

## Control console (multi-phase)

A web control console: register/login, a chat-testing UI, and an admin area to
insert/manage RAG texts, visualise chunking, and toggle texts on/off.

- **Phase 1 — backend RAG engine + document model.** ✅ **built**: hybrid
  (dense + BM25 sparse + RRF), Adaptive-RAG classifier routing, local Qwen3
  rerank, per-type chunking (slides/prose/token), `documents` registry +
  enable/disable, admin doc/chunk APIs (`GET /documents`,
  `GET /documents/{id}/chunks`, `PATCH` toggle, `POST /ingest/pptx`).
- **Phase 2 — auth + unified API.** ✅ **built**: JWT bearer auth, `users` table
  (first-user-admin), single `interfaces/api_app.py` (`/auth/register|login|me` +
  `/chat` + admin-gated `/documents`/`/ingest`) replacing http_app + admin_app.
  Remaining auth polish (deferred): refresh tokens, rate limiting, password reset.
- **Phase 3 — frontend.** SPA: auth pages, chat UI, admin console (upload/manage
  texts), chunk visualiser (vector-DB-style; feed = `GET /documents/{id}/chunks`),
  per-text enable/disable toggle. Consumes the Phase-2 API.

## Front-end adapters

- **Discord adapter** — ✅ **built** (`interfaces/discord_app.py`): a `discord.py`
  gateway bot. Replies on @mention (guild) / every DM; per-message `OutboundWaiter`
  await with a typing indicator; live status as a self-cleaning reaction
  (👀→🧠→tool emoji→✅) driven by the worker's pub/sub progress channel.
- **Line adapter** — not built yet: a webhook FastAPI process — receive Line
  events, normalise to an `InboundEvent`, publish to `chat:inbound`; consume
  `chat:outbound` and send via Line reply/push API. (Note: Line is request/reply
  over HTTP, so it can reuse the `OutboundWaiter` pattern like the HTTP gateway,
  or push asynchronously.)

Ready: the event contract (`shared/events.py` — `InboundEvent`/`OutboundEvent`
with `platform`/`channel_id`/`user_id`/`correlation_id`/`reply_token`) and the
identity model (per-channel memory, per-user facts) already support groups. Each
adapter uses its own outbound consumer group. The core needs no changes. The
Discord adapter is the reference for a new platform.

## Tier-4 RAG growth

Done (Phase 1): hybrid dense+BM25/RRF, Adaptive-RAG classifier routing, Qwen3
rerank, per-type chunking, document enable/disable. Remaining:

- **More chunk strategies** — the registry (`core/rag/chunkers.py`) is keyed by
  `doc_type`; add PDF, Markdown/HTML, code, transcripts, etc. (slides + prose +
  token exist).
- **Auto-distilled experiences** — an LLM distills a reusable "case card" and
  embeds it under `source="distilled_experience"` (payload reserves `source`).
- **Per-user conversation RAG** — retrieve a speaker's own past conversations;
  the retriever would add a `user_key` filter for this source.

## Tools

- **`get_member_memory` tool** — let the model fetch another group member's
  personal memory mid-reply (originally deferred until groups exist). The
  tool-calling loop is built; this is one new `@tool` handler.
- **Multi-provider tool-calling** — Gemini / Ollama / Anthropic currently fall
  back to plain text. Implement `complete(messages, tools)` + `supports_tools`
  per provider to enable tools there.

## Cross-cutting

- **Streaming replies** (token streaming through the gateway).
- **Auth + rate limiting** on the chat gateway and `/ingest`.
- **Ingest hardening** — authentication, file parsing (PDF/HTML/Markdown), batch
  uploads, delete/list endpoints.
- **Message dedupe** — use `platform_message_id` to drop duplicate inbound events
  (relevant once real adapters with retries exist).
- **Containerise app processes** + orchestration manifests; **CI** (run
  `pytest -m "not integration"` on push, integration on a service-backed job);
  metrics/tracing.

## Tuning backlog (no new features, just calibration)

- `fact_system_prompt` — sharpen replace-vs-retire wording to reduce the
  over-retire tendency (a code guard already prevents data loss; the prompt could
  prevent the contradictory delta in the first place).
- `RAG_SCORE_THRESHOLD` — currently 0; calibrate after observing real score
  distributions to filter weak hits.
- Channel-summary length — currently controlled by prompt + render truncation;
  consider a per-call `max_tokens` cap on the summary completion.
