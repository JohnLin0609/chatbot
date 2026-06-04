# Chatbot Control Console

A layered, multi-tier-memory chatbot **plus a web control console**. A
platform-agnostic **core** owns conversation behaviour (4 memory tiers,
summarisation, Adaptive-RAG) and talks to a switchable LLM; **adapters** (a unified
HTTP API, CLI, Discord) connect front-ends over **Redis Streams**. Durable state
lives in **PostgreSQL** + **Qdrant**; hot context in **Redis**. A **React SPA**
(`frontend/`) drives it: login, chat tester, and an admin console for RAG content.

See [docs/architecture.md](docs/architecture.md) for the full design and
[docs/](docs/) for development, deployment, decisions, and roadmap.

```
SPA / API / CLI / Discord ──XADD──▶ chat:inbound ──▶ core worker ──▶ LLM
        ▲                                                │
        └─────────────  chat:outbound  ◀──XADD──────────┘
```

The LLM provider is switchable between **Anthropic / OpenAI / Gemini / Ollama**.

## What it does

- **4 memory tiers**: tier-1 recent-context window, tier-2 per-channel running
  summary, tier-3 durable per-user fact document (JSONB), tier-4 RAG.
- **Adaptive-RAG**: an LLM classifier routes each query `simple` (no retrieval) /
  `medium` (hybrid retrieve → top 3) / `complex` (hybrid → Qwen3 rerank → top 3).
  Retrieval is **hybrid** (dense + BM25 sparse + RRF) over Qdrant; per-document-type
  chunking (slides `.pptx` / prose via spaCy / token); documents toggle on/off.
- **Session lifecycle**: 10-min hot-cache TTL; a worker **idle-sweeper** finalises
  ended sessions into tier-2 summary + tier-3 facts so short chats still persist.
- **Auth**: JWT bearer; first registered account is admin; admin gates RAG management.
- **Tools**: extensible tool-calling loop; `web_search` (Brave) when keyed.
- **Discord** adapter with live reaction status; **CLI** for local testing.

## Layout

```
core/
  llm/ memory/ summary/ facts/ tokens/         conversation behaviour + memory
  tools/        tool registry + tool-calling loop (extensible)
  rag/          embeddings, Qdrant store (hybrid), chunkers, ingest, classifier,
                retriever, reranker (Qwen3)
  web/          Brave web_search tool/service
  documents/    document registry (enable/disable)
  auth/         password hashing, JWT, user store, FastAPI deps
  session/      idle-session finalizer
  persistence/  SQLAlchemy models + repository
  pipeline.py runtime.py
interfaces/
  worker.py     core consumer (inbound -> pipeline -> outbound) + finalize sweeper
  api_app.py    unified JWT API: /auth/* + /chat + admin-gated /documents,/ingest
  discord_app.py  Discord gateway bot
  cli.py        local fake adapter
shared/       event contracts, redis client, progress channel
migrations/   Alembic (0001..0005)
frontend/     React + Vite + TS + Tailwind SPA (chat + admin console)
docs/         architecture, development, deployment, decisions, roadmap, progress
```

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
python -m spacy download xx_sent_ud_sm     # prose chunking (optional; falls back to token)
cp .env.example .env                        # set OPENAI_API_KEY + JWT_SECRET (+ others)
docker compose up -d                        # redis (6380) + postgres (5434) + qdrant (6333)
alembic upgrade head                        # create tables
```

Redis/Postgres use **dedicated host ports 6380/5434** (not 6379/5432); Qdrant uses
6333. Heavy RAG deps (`fastembed`, `torch`+`transformers` for the reranker) are
optional and degrade gracefully. The reranker downloads `Qwen/Qwen3-Reranker-0.6B`
(~1.2 GB) on first use.

## Run

```bash
python -m interfaces.worker                    # core worker + idle-session sweeper
uvicorn interfaces.api_app:app --port 8753     # unified JWT API
python -m interfaces.discord_app               # Discord bot (needs DISCORD_BOT_TOKEN)
python -m interfaces.cli --session web:c1      # CLI (optional, unauthenticated)
cd frontend && npm install && npm run dev       # web console on http://localhost:5173
```

### Try it (API)

```bash
# register the FIRST account (becomes admin) and grab the token
TOKEN=$(curl -s -X POST localhost:8753/auth/register -H 'Content-Type: application/json' \
  -d '{"email":"me@x.com","password":"password123"}' | python -c 'import sys,json;print(json.load(sys.stdin)["access_token"])')

# ingest curated knowledge (admin-only)
curl -X POST localhost:8753/ingest -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"title":"Refund Policy","text":"Customers may request a refund within 14 days.","doc_type":"prose"}'

# chat (authenticated; ties to per-user memory)
curl -X POST localhost:8753/chat -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"message":"How long do I have to request a refund?","conversation_id":"c1"}'
```

Or just open the SPA at `localhost:5173`, register, and use the Chat / Admin tabs.

## Configuration

Key settings (see `.env.example` for all). Only the API key for the selected
provider is required; set a strong `JWT_SECRET` for the API.

| Variable | Default | Description |
| --- | --- | --- |
| `PROVIDER` / `MODEL` | `anthropic` / per-provider | LLM provider + model |
| `OPENAI_API_KEY` | — | chat (if openai) + embeddings |
| `JWT_SECRET` | — | API token signing (set in prod) |
| `REDIS_URL` / `POSTGRES_DSN` / `QDRANT_URL` | dedicated ports | backing stores |
| `HOT_TTL_SECONDS` | `600` | session hot-cache TTL (10 min) |
| `USER_MEMORY_TTL_SECONDS` | `604800` | tier-3 mirror TTL (decoupled) |
| `SESSION_FINALIZE_IDLE_SECONDS` | `600` | idle → finalize threshold |
| `CONTEXT_WINDOW_TOKENS` / `FACT_EXTRACTION_TOKENS` | `3000` / `6000` | tier-1 / tier-3 water-levels |
| `RAG_RERANKER_MODEL` | `Qwen/Qwen3-Reranker-0.6B` | complex-tier reranker |
| `BRAVE_API_KEY` / `DISCORD_BOT_TOKEN` | — | optional `web_search` / Discord |

## Tests

```bash
pytest -m "not integration"        # backend unit (mocked redis/db/LLM)
pytest -m integration              # backend integration (needs docker compose up)
cd frontend && npm run test        # frontend (Vitest)
```
