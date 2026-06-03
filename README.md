# Chatbot Backend

A layered chatbot backend. A platform-agnostic **core** owns conversation
behaviour (memory, summarisation, session management) and talks to an LLM; thin
**adapters** (HTTP, CLI now; Line/Discord later) connect front-ends. Core and
adapters communicate asynchronously over **Redis Streams**; durable history
lives in **PostgreSQL**, hot context in **Redis**.

See [docs/architecture.md](docs/architecture.md) for the full design.

```
adapter (http/cli/…)  ──XADD──▶  chat:inbound  ──▶  core worker  ──▶  LLM
        ▲                                              │
        └────────  chat:outbound  ◀──XADD─────────────┘
```

The LLM provider is switchable between **Anthropic**, **OpenAI**, **Gemini**,
and **Ollama** (local) via configuration.

## Layout

```
core/         platform-agnostic domain logic
  llm/        provider abstraction (anthropic/openai/gemini/ollama) + tool-calling
  memory/     Redis hot store + context builder
  summary/    running-summary maintenance
  facts/      per-user durable fact memory (tier-3)
  tokens/     tiktoken counting
  tools/      tool registry + tool-calling loop (extensible)
  rag/        embeddings + Qdrant store + chunking + ingest + search_knowledge tool
  persistence/ SQLAlchemy models + repository
  pipeline.py one inbound event -> one outbound event
  runtime.py  wire deps together
interfaces/   process entrypoints
  worker.py   core consumer (inbound -> pipeline -> outbound)
  http_app.py FastAPI gateway: POST /chat (async round-trip)
  admin_app.py FastAPI admin: POST /ingest (curated knowledge)
  cli.py      fake adapter for local testing
  correlation.py  match outbound events back to requests
shared/       cross-process contracts (events, redis client, stream names)
migrations/   Alembic
```

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-dev.txt

cp .env.example .env          # set the API key for your chosen PROVIDER
docker compose up -d          # redis + postgres + qdrant (this project's own)
alembic upgrade head          # create tables
```

Redis and Postgres run on **dedicated host ports 6380 and 5434** (not the
conventional 6379/5432) so they never collide with another instance on your
machine; Qdrant uses the standard 6333. The app's defaults point at these ports.

## Run

Local processes (each in its own terminal):

```bash
python -m interfaces.worker                       # 1) core worker
uvicorn interfaces.http_app:app --port 8753       # 2) chat gateway
uvicorn interfaces.admin_app:app --port 8754      # 3) admin (knowledge ingest)
python -m interfaces.cli --session line:c1        # 4) CLI (optional)
```

### Try it

```bash
# memory across turns
curl -X POST localhost:8753/chat -H "Content-Type: application/json" \
  -d '{"session_id":"line:c1","message":"記住我叫小明"}'
curl -X POST localhost:8753/chat -H "Content-Type: application/json" \
  -d '{"session_id":"line:c1","message":"我叫什麼？"}'   # 應答出「小明」

# RAG: ingest a curated doc, then ask about it
curl -X POST localhost:8754/ingest -H "Content-Type: application/json" \
  -d '{"title":"退款政策","text":"顧客可在購買後 14 天內申請全額退款。"}'
curl -X POST localhost:8753/chat -H "Content-Type: application/json" \
  -d '{"session_id":"line:c1","message":"退款要幾天內申請？"}'  # 模型呼叫 search_knowledge
```

`session_id` is the conversation key (`platform:channel_id`). The core keeps
three token-driven memory tiers (recent-context window, per-channel running
summary, durable **per-user fact document**) plus **tier-4 RAG**: the model can
call the `search_knowledge` tool to retrieve curated knowledge ingested via
`POST /ingest`. See [docs/architecture.md](docs/architecture.md).

## Configuration

Key settings (see `.env.example` for all). Only the API key for the selected
provider is required.

| Variable                | Default                                            | Description                       |
| ----------------------- | -------------------------------------------------- | --------------------------------- |
| `PROVIDER`              | `anthropic`                                        | `anthropic`/`openai`/`gemini`/`ollama` |
| `MODEL`                 | per-provider default                               | Model name (empty = default)      |
| `REDIS_URL`             | `redis://localhost:6380/0`                         | Redis (streams + hot store)       |
| `POSTGRES_DSN`          | `postgresql+asyncpg://chat:chat@localhost:5434/chat` | Durable history                 |
| `CONTEXT_WINDOW_TOKENS` | `3000`                                             | Tier-1 recent-context window      |
| `CHANNEL_SUMMARY_TOKEN_CAP` | `150`                                          | Tier-2 channel summary size       |
| `FACT_EXTRACTION_TOKENS`| `6000`                                             | Tier-3 fact-extraction water-level|
| `PERSONAL_MEMORY_TOKEN_CAP` | `800`                                          | Injected per-user memory cap      |
| `QDRANT_URL`            | `http://localhost:6333`                            | Vector store (tier-4 RAG)         |
| `EMBEDDING_MODEL`       | `text-embedding-3-small`                           | Embedding model (fixed per collection) |
| `ENABLE_TOOLS`          | `true`                                             | Tool-calling on the main reply    |
| `RAG_TOP_K`             | `5`                                                | search_knowledge result count     |
| `HOT_TTL_SECONDS`       | `604800`                                           | Hot-store TTL (7 days)            |
| `REPLY_TIMEOUT_SECONDS` | `30`                                               | Gateway wait for a reply          |

## Tests

```bash
pytest -m "not integration"   # unit tests (mocked redis/db/LLM)
pytest -m integration         # needs `docker compose up -d`
```
