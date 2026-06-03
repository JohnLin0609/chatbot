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
  llm/        provider abstraction (anthropic/openai/gemini/ollama)
  memory/     Redis hot store + context builder
  summary/    running-summary maintenance
  persistence/ SQLAlchemy models + repository
  pipeline.py one inbound event -> one outbound event
  runtime.py  wire deps together
interfaces/   process entrypoints
  worker.py   core consumer (inbound -> pipeline -> outbound)
  http_app.py FastAPI gateway: POST /chat (async round-trip)
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
docker compose up -d          # redis + postgres (this project's own)
alembic upgrade head          # create tables
```

This project's Redis and Postgres run on **dedicated host ports 6380 and 5434**
(not the conventional 6379/5432) so they never collide with another Redis or
Postgres already running on your machine. The app's defaults point at these
ports.

## Run

Three local processes (each in its own terminal):

```bash
python -m interfaces.worker                       # 1) core worker
uvicorn interfaces.http_app:app --port 8753       # 2) HTTP gateway
python -m interfaces.cli --session line:c1        # 3) CLI (optional)
```

### Try it

```bash
curl -X POST localhost:8753/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"line:c1","message":"記住我叫小明"}'

curl -X POST localhost:8753/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"line:c1","message":"我叫什麼？"}'   # 應答出「小明」(memory)
```

`session_id` is the conversation key (`platform:channel_id`). Memory is shared
per channel. After more than `SUMMARY_TRIGGER_TURNS` turns the core folds older
turns into a running summary (check the `summaries` table).

## Configuration

Key settings (see `.env.example` for all). Only the API key for the selected
provider is required.

| Variable                | Default                                            | Description                       |
| ----------------------- | -------------------------------------------------- | --------------------------------- |
| `PROVIDER`              | `anthropic`                                        | `anthropic`/`openai`/`gemini`/`ollama` |
| `MODEL`                 | per-provider default                               | Model name (empty = default)      |
| `REDIS_URL`             | `redis://localhost:6380/0`                         | Redis (streams + hot store)       |
| `POSTGRES_DSN`          | `postgresql+asyncpg://chat:chat@localhost:5434/chat` | Durable history                 |
| `RECENT_TURNS`          | `4`                                                | Recent turns fed to the LLM       |
| `HOT_TTL_SECONDS`       | `604800`                                           | Hot-store TTL (7 days)            |
| `SUMMARY_TRIGGER_TURNS` | `10`                                               | Turns before summarising          |
| `REPLY_TIMEOUT_SECONDS` | `30`                                               | Gateway wait for a reply          |

## Tests

```bash
pytest -m "not integration"   # unit tests (mocked redis/db/LLM)
pytest -m integration         # needs `docker compose up -d`
```
