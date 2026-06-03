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

cp .env.example .env                   # set OPENAI_API_KEY (and PROVIDER/MODEL if not OpenAI)
docker compose up -d                   # redis (6380), postgres (5434), qdrant (6333)
alembic upgrade head                   # create tables
```

The app's config defaults point at the compose services. Redis/Postgres use
**dedicated host ports 6380/5434** (not 6379/5432) to avoid colliding with other
instances; Qdrant uses the standard 6333. Override via env (`REDIS_URL`,
`POSTGRES_DSN`, `QDRANT_URL`).

## Running the processes

Each is a separate long-running process (own terminal):

```bash
python -m interfaces.worker                   # core consumer: inbound stream -> pipeline -> outbound
uvicorn interfaces.http_app:app --port 8753   # chat gateway: POST /chat (async, waits for reply)
uvicorn interfaces.admin_app:app --port 8754  # admin: POST /ingest (curated knowledge)
python -m interfaces.cli --session line:c1    # optional: fake adapter driving the streams
python -m interfaces.discord_app              # Discord bot (needs DISCORD_BOT_TOKEN)
```

The worker and admin app call `ensure_collection()` on Qdrant at startup.

### Quick manual checks

```bash
# chat (memory across turns)
curl -X POST localhost:8753/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"line:c1","message":"remember my name is Sam"}'

# ingest + RAG
curl -X POST localhost:8754/ingest -H 'Content-Type: application/json' \
  -d '{"title":"Refund Policy","text":"Customers may request a refund within 14 days."}'
curl -X POST localhost:8753/chat -H 'Content-Type: application/json' \
  -d '{"session_id":"line:c1","message":"how long do I have to request a refund?"}'
```

The worker logs `tool call: search_knowledge ...` when the model uses RAG.

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
their decorators run, then registers them. `core/rag/search_tool.py` is the
reference example. The OpenAI provider already supports the tool loop; nothing
else needs changing.

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
