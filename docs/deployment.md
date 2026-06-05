# Deployment guide

How to bring the system up on another machine. There is no container image for
the app processes yet (see [roadmap.md](roadmap.md)); you run them from a Python
environment, while Redis/Postgres/Qdrant run via Docker Compose.

## Prerequisites

- Docker + Docker Compose (Redis, Postgres, Qdrant)
- Python 3.12 (to run worker / gateways), or wrap them yourself in a container
- An `OPENAI_API_KEY` (chat default provider + embeddings)
- For the full RAG engine: the heavy deps `fastembed` (BM25), `spacy` +
  `python -m spacy download xx_sent_ud_sm` (prose chunking), and
  `torch`+`transformers` (Qwen3 reranker, downloads ~1.2 GB on first use, GPU
  optional). All are **optional** — the engine degrades to dense-only / token
  chunking / no-rerank without them.

## 1. Backing services

```bash
docker compose up -d            # redis, postgres, qdrant
docker compose ps               # all healthy?
```

`docker-compose.yml` publishes **dedicated host ports** to avoid collisions on a
shared box:

| Service | Container port | Host port | Notes |
| --- | --- | --- | --- |
| redis | 6379 | **6380** | streams + hot store |
| postgres | 5432 | **5434** | durable; volume `pgdata` |
| qdrant | 6333/6334 | **6333**/6334 | vectors; volume `qdrant_data` |

To change ports/hosts (e.g. managed Redis/Postgres, remote Qdrant), set the
connection env vars instead of editing compose — the app reads them from `.env`.

### All-in-one (dev / single box): the `app` profile

For a self-contained bring-up, the app processes are also dockerised behind a
compose `app` profile:

```bash
docker compose --profile app up -d --build   # migrate + worker + api + frontend
# console on http://localhost:8080, API on :8753
```

This runs the migration (one-shot), worker, API, and the nginx-served SPA in
containers, with store URLs auto-pointed at the in-network services. It's a
convenience for dev/single-box use — **not** production-hardened (no TLS, runs as
root, single replica). For production prefer the per-process model in §4 behind
your own edge/TLS, and scale workers as N replicas.

## 2. Configuration & secrets

Copy `.env.example` to `.env` and set at least:

| Var | Required | Purpose |
| --- | --- | --- |
| `OPENAI_API_KEY` | yes (OpenAI provider/embeddings) | API key |
| `PROVIDER` / `MODEL` | optional | LLM provider + model (default openai / gpt-4o-mini; this project ran gpt-5.4-mini) |
| `REDIS_URL` | yes | e.g. `redis://localhost:6380/0` |
| `POSTGRES_DSN` | yes | e.g. `postgresql+asyncpg://chat:chat@localhost:5434/chat` |
| `QDRANT_URL` | yes (for RAG) | e.g. `http://localhost:6333` |
| `EMBEDDING_MODEL` / `EMBEDDING_DIM` | optional | must stay fixed for a given Qdrant collection |
| `BRAVE_API_KEY` | optional | enables the `web_search` tool (unset = tool disabled) |
| `DISCORD_BOT_TOKEN` | optional | required to run the Discord adapter (Message Content Intent must be enabled) |
| `JWT_SECRET` | yes (for the API) | long random value (>=32 bytes); if unset, tokens use an ephemeral dev secret and don't survive a restart |
| `AUTH_OPEN_REGISTRATION` | optional | `true` (default) allows self-registration; first account becomes admin |

**Never commit `.env`** (it's gitignored). Change the Postgres credentials from
the `chat:chat` default for anything beyond local use.

## 3. Database migration

```bash
alembic upgrade head            # sessions/messages/summaries/user_memory/documents/users
```

Re-run after pulling new migrations. Qdrant's `knowledge` collection is created
automatically by the worker / API app on startup (no manual step).

> **Breaking schema change:** the collection now uses **named dense + BM25 sparse
> vectors**. An existing single-vector `knowledge` collection is incompatible —
> drop it (and re-ingest curated docs) before upgrading. `ensure_collection` only
> creates when missing, so a stale collection must be deleted manually.

## 4. Processes to run

| Process | Command | Notes |
| --- | --- | --- |
| Core worker | `python -m interfaces.worker` | The brain. Run **N replicas** to scale — they share the `core-workers` consumer group on `chat:inbound`, so work is load-balanced and a crashed worker's messages are reclaimed (`XAUTOCLAIM`). Each worker also runs the **idle-session sweeper** (folds ended sessions into durable memory); harmless if several run it. |
| Console API | `uvicorn interfaces.api_app:app --port 8753` | JWT-authenticated: `/auth/*`, `/chat` (any user), `/documents`+`/ingest` (admin). Stateless; put behind your public edge / TLS. Replaces the old chat (8753) + admin (8754) apps. |
| CLI | `python -m interfaces.cli` | Optional local/manual driver (publishes to streams directly; no auth). |
| Discord bot | `python -m interfaces.discord_app` | Persistent gateway bot (own `discord-gateway` consumer group). Needs `DISCORD_BOT_TOKEN` + Message Content Intent. Run **one** instance (a second would double-handle messages). |

Startup ordering: bring up services + run migrations first, then workers, then
gateways. Workers and the gateway can start in any order (they rendezvous via
Redis streams); a gateway request will time out (504) if no worker is consuming.

### Frontend (control console SPA)

```bash
cd frontend
npm ci
VITE_API_BASE_URL=https://api.example.com npm run build   # -> frontend/dist/
```

Serve the static `dist/` from any static host / CDN / edge (nginx, etc.), or your
reverse proxy. Set `VITE_API_BASE_URL` (at build time) to the public API origin;
the API's CORS currently allows all origins (tighten for production).

## 5. Operational notes

- **Scaling**: add worker replicas for throughput (consumer group handles
  distribution). The gateway is stateless — scale horizontally behind a load
  balancer; each instance runs its own `OutboundWaiter` (uses the
  `http-gateway` consumer group).
- **Health**: `GET /health` on the API (8753).
- **Eval judging**: the LLM-as-judge runs offline — `python -m interfaces.judge
  --all` (or admin `POST /admin/eval/judge`) to score new traces. It is batch /
  on-demand, not a long-running service.
- **nginx upstream after recreating the API (compose `app` profile)**: the
  `frontend` nginx resolves `api` once and caches its container IP. If you rebuild
  /recreate only the `api` service, its IP changes and nginx serves 502 until you
  `docker compose --profile app restart frontend` (or recreate both together).
- **Persistence**: Postgres (`pgdata`) and Qdrant (`qdrant_data`) are Docker
  volumes — back them up. Redis is hot cache + transient streams; losing it
  loses in-flight messages and hot context (rebuilt from Postgres on next turn),
  not durable history.
- **Embedding model is fixed per collection**: never change `EMBEDDING_MODEL` /
  `EMBEDDING_DIM` against an existing `knowledge` collection — re-ingest into a
  fresh collection instead.

## Known gaps (before production)

- JWT auth gates the API, but no rate limiting / refresh tokens / password reset
  yet. Set a strong `JWT_SECRET` and `AUTH_OPEN_REGISTRATION=false` once the admin
  account exists if the API is exposed.
- App processes not containerised; no orchestration manifests.
- No CI/CD; no metrics/tracing.

See [roadmap.md](roadmap.md).
