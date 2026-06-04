# Development guide

## Prerequisites

- Python 3.12
- Docker + Docker Compose (for Redis, Postgres, Qdrant)
- An `OPENAI_API_KEY` (the default provider; embeddings also use OpenAI)

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt   # includes runtime deps + pytest/fakeredis/aiosqlite
python -m spacy download xx_sent_ud_sm  # multilingual sentence splitter (prose chunking)

cp .env.example .env                   # set OPENAI_API_KEY (and PROVIDER/MODEL if not OpenAI)
docker compose up -d                   # redis (6380), postgres (5434), qdrant (6333)
alembic upgrade head                   # create tables (incl. `documents`)
```

Heavy RAG deps (`fastembed` for BM25, `torch`+`transformers` for the Qwen3
reranker, `spacy`) are optional — the engine degrades gracefully without them
(dense-only retrieval / no rerank / token chunking). The first reranker use
downloads `Qwen/Qwen3-Reranker-0.6B` (~1.2 GB). The `knowledge` Qdrant collection
now uses **named dense + BM25 sparse vectors**; if you have an old single-vector
collection, drop it and re-ingest.

The app's config defaults point at the compose services. Redis/Postgres use
**dedicated host ports 6380/5434** (not 6379/5432) to avoid colliding with other
instances; Qdrant uses the standard 6333. Override via env (`REDIS_URL`,
`POSTGRES_DSN`, `QDRANT_URL`).

## Running everything in Docker

The full stack is dockerised behind an `app` compose profile (the backend image
bundles the heavy RAG deps, so the build is slow and multi-GB the first time):

```bash
docker compose --profile app up -d --build   # migrate -> worker + api + frontend
# console: http://localhost:8080   (API also published on :8753 for curl/debug)
docker compose --profile app down            # stop the app services
docker compose up -d                         # infra-only (dev habit, no profile)
```

One backend image serves three roles via the compose `command:` — a one-shot
`migrate` (`alembic upgrade head`) that worker/api wait on
(`service_completed_successfully`), the `worker`, and the `api`. The `frontend`
service is nginx serving the built SPA and reverse-proxying the API (single
origin → no CORS). Store URLs are overridden in compose to service names
(`redis:6379` / `postgres:5432` / `qdrant:6333`); `.env` only needs a provider
key + `JWT_SECRET`. Model weights persist in the `hf_cache` volume. The Discord
bot is not in the profile.

## Running the processes by hand (local dev)

Each is a separate long-running process (own terminal):

```bash
python -m interfaces.worker                   # core consumer: inbound stream -> pipeline -> outbound
uvicorn interfaces.api_app:app --port 8753    # unified API: /auth/* + /chat + admin docs/ingest
python -m interfaces.cli --session line:c1    # optional: fake adapter driving the streams
python -m interfaces.discord_app              # Discord bot (needs DISCORD_BOT_TOKEN)
```

The worker and the API app call `ensure_collection()` on Qdrant at startup. The
API is JWT-authenticated; CLI/Discord publish to the streams directly (no auth).

### Frontend (control console SPA)

```bash
cd frontend
npm install
npm run dev          # Vite dev server on http://localhost:5173
npm run test         # Vitest (jsdom) unit/component tests
npm run build        # type-check + build to dist/
```

React + Vite + TypeScript + Tailwind. It calls the API at `VITE_API_BASE_URL`
(default `http://localhost:8753`; copy `.env.example` to `.env` to override).
Open `localhost:5173`, **register the first account** (becomes admin), then chat
or use the **Admin** tab to upload knowledge, toggle documents, and inspect
chunks. JWT is kept in `localStorage`; a 401 bounces you to `/login`.

### Quick manual checks

```bash
# register the FIRST account (becomes admin) and capture the token
TOKEN=$(curl -s -X POST localhost:8753/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"me@x.com","password":"password123"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')
curl localhost:8753/auth/me -H "Authorization: Bearer $TOKEN"

# ingest curated knowledge (admin-only)
curl -X POST localhost:8753/ingest -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"title":"Refund Policy","text":"Customers may request a refund within 14 days.","doc_type":"prose"}'
curl -X POST localhost:8753/ingest/pptx -H "Authorization: Bearer $TOKEN" -F file=@deck.pptx -F title="Onboarding"

# manage documents (admin)
curl localhost:8753/documents -H "Authorization: Bearer $TOKEN"               # list
curl localhost:8753/documents/<doc_id>/chunks -H "Authorization: Bearer $TOKEN"  # visualiser feed
curl -X PATCH localhost:8753/documents/<doc_id> -H "Authorization: Bearer $TOKEN" \
  -H 'Content-Type: application/json' -d '{"enabled": false}'                 # disable in retrieval

# chat (authenticated; user_id ties to the account -> tier-3 memory)
curl -X POST localhost:8753/chat -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"message":"how long do I have to request a refund?","conversation_id":"c1"}'
```

Knowledge RAG is **Adaptive-RAG** (not a tool): a classifier routes the query to
`simple` (no retrieval) / `medium` (hybrid → fused Top 3) / `complex` (hybrid →
Qwen3 rerank → Top 3), injected into the prompt. The worker logs `tool call:
web_search ...` for the live-web tool.

### Discord adapter

1. Create an application + bot at the Discord Developer Portal; copy the bot token
   to `DISCORD_BOT_TOKEN` in `.env`.
2. Under **Bot → Privileged Gateway Intents**, enable **Message Content Intent**
   (required to read message text for the @mention/DM trigger).
3. Invite the bot with the `bot` scope and permissions to read/send messages and
   add reactions.
4. Run `python -m interfaces.discord_app` alongside the worker. @mention the bot
   in a channel, or DM it. Status shows as a self-cleaning reaction on your
   message (👀→🧠→tool emoji→✅); per-tool reactions (e.g. 🌐 for `web_search`)
   are driven live by the worker's pub/sub progress channel (`PROGRESS_CHANNEL`).
   Optionally restrict to specific servers via `DISCORD_ALLOWED_GUILDS` (CSV).

## Tests

```bash
pytest -m "not integration"   # unit tests (default); no Docker/network needed
pytest -m integration         # needs docker compose up (redis+postgres+qdrant) and an API key
```

Conventions for tests (`tests/conftest.py`):
- **fakeredis** for Redis, **SQLite in-memory with `StaticPool`** for Postgres
  (single shared connection so background-task sessions see the same DB).
- **`FakeChat`** stands in for the LLM. It sets `supports_tools=False` so the
  tool loop takes its fallback path — keeping plain-reply assertions stable.
  `FakeEmbedding` / `FakeVectorStore` stand in for RAG.
- `make_settings(**overrides)` builds `Settings` with small token windows so
  overflow/extraction trigger quickly.

## Project layout

See [architecture.md](architecture.md) for the full picture. Briefly:
`core/` (domain: `llm/ memory/ summary/ facts/ tokens/ tools/ rag/ persistence/`
+ `pipeline.py`, `runtime.py`), `interfaces/` (process entrypoints), `shared/`
(event contracts + Redis helpers), `migrations/` (Alembic).

## Extending the system

### Add a new tool
Tools are auto-discovered. Define an async handler decorated with `@tool(...)`:

```python
# core/tools/<your_tool>.py  (and import it in register_default_tools)
from core.tools.registry import tool
from core.tools.schemas import ToolContext

@tool(name="get_weather",
      description="Get current weather for a city.",
      parameters={"type": "object",
                  "properties": {"city": {"type": "string"}},
                  "required": ["city"]})
async def get_weather(args: dict, ctx: ToolContext) -> str:
    ...  # ctx gives settings, embedding_service, vector_store, session/user ids
    return "..."  # text the LLM sees
```

`register_default_tools` (in `core/tools/registry.py`) imports tool modules so
their decorators run, then registers them. `core/web/search_tool.py` (Brave
`web_search`) is the reference example. The OpenAI provider already supports the
tool loop; nothing else needs changing.

To gate a tool on configuration (e.g. an API key), add a predicate:
`@tool(..., requires=lambda s: bool(s.brave_api_key))` — the tool is registered
only when it returns truthy, so the model never sees a tool it can't use.
`core/web/search_tool.py` (Brave `web_search`) is the reference example; its
`BraveSearchService` is built in `runtime.py` and injected via `ToolContext`
(the same pattern as `embedding_service` / `vector_store`).

### Add an LLM provider
Subclass `ChatService` (`core/llm/base.py`), implement `generate_reply`; to
support tools also set `supports_tools = True` and implement `complete(messages,
tools)` returning a `ChatCompletionResult`. Register the class in
`core/llm/factory.py::_SERVICES` and add a default model in
`core/config.py::DEFAULT_MODELS`. Providers without `complete` inherit a
text-only fallback automatically.

### Add a DB migration
Edit `core/persistence/models.py`, then add
`migrations/versions/000N_<name>.py` (set `down_revision` to the previous id).
Use the `BigIntPK` and `JsonDoc` variants for any new PK / JSON column so the
SQLite-backed tests keep working. Apply with `alembic upgrade head`.

### Add a config setting
Add a field to `core/config.py::Settings` (pydantic-settings reads the uppercase
env var automatically) and document it in `.env.example`.

## Conventions worth knowing

- **Sizing is token-based** (tiktoken via `core/tokens/counter.py`), not turn
  counts. Windowing is always whole-turn (`core/memory/token_window.py`).
- **Two identities**: `session_id = platform:channel_id` (tiers 1-2),
  `user_key = platform:user_id` (tiers 3-4).
- **Don't change `ChatService.generate_reply`** — tier-2/3 depend on it. New
  capabilities go through `complete(messages, tools)`.
- **Tier 1-3 are injected directly** into the prompt; **RAG is tool-only** (no
  auto-prefetch). The model decides when to retrieve.
- **The extraction cursor invariant**: `user_memory.last_extracted_message_id`
  advances only after a successful fact extraction, so messages evicted from the
  window but not yet extracted are never lost (they stay in Postgres `messages`).
