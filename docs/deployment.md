# Deployment guide

How to bring the system up on another machine. There is no container image for
the app processes yet (see [roadmap.md](roadmap.md)); you run them from a Python
environment, while Redis/Postgres/Qdrant run via Docker Compose.

## Prerequisites

- Docker + Docker Compose (Redis, Postgres, Qdrant)
- Python 3.12 (to run worker / gateways), or wrap them yourself in a container
- An `OPENAI_API_KEY` (chat default provider + embeddings)

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

**Never commit `.env`** (it's gitignored). Change the Postgres credentials from
the `chat:chat` default for anything beyond local use.

## 3. Database migration

```bash
alembic upgrade head            # creates sessions/messages/summaries/user_memory
```

Re-run after pulling new migrations. Qdrant's `knowledge` collection is created
automatically by the worker/admin app on startup (no manual step).

## 4. Processes to run

| Process | Command | Notes |
| --- | --- | --- |
| Core worker | `python -m interfaces.worker` | The brain. Run **N replicas** to scale — they share the `core-workers` consumer group on `chat:inbound`, so work is load-balanced and a crashed worker's messages are reclaimed (`XAUTOCLAIM`). |
| Chat gateway | `uvicorn interfaces.http_app:app --port 8753` | Stateless; put behind your public edge / TLS. Publishes inbound, waits for the correlated outbound. |
| Admin (ingest) | `uvicorn interfaces.admin_app:app --port 8754` | Internal-only — **do not expose publicly** (no auth yet). |
| CLI | `python -m interfaces.cli` | Optional local/manual driver. |

Startup ordering: bring up services + run migrations first, then workers, then
gateways. Workers and the gateway can start in any order (they rendezvous via
Redis streams); a gateway request will time out (504) if no worker is consuming.

## 5. Operational notes

- **Scaling**: add worker replicas for throughput (consumer group handles
  distribution). The gateway is stateless — scale horizontally behind a load
  balancer; each instance runs its own `OutboundWaiter` (uses the
  `http-gateway` consumer group).
- **Health**: `GET /health` on both gateway (8753) and admin (8754).
- **Persistence**: Postgres (`pgdata`) and Qdrant (`qdrant_data`) are Docker
  volumes — back them up. Redis is hot cache + transient streams; losing it
  loses in-flight messages and hot context (rebuilt from Postgres on next turn),
  not durable history.
- **Embedding model is fixed per collection**: never change `EMBEDDING_MODEL` /
  `EMBEDDING_DIM` against an existing `knowledge` collection — re-ingest into a
  fresh collection instead.

## Known gaps (before production)

- No authentication / rate limiting on the gateway or `/ingest`.
- App processes not containerised; no orchestration manifests.
- No CI/CD; no metrics/tracing.

See [roadmap.md](roadmap.md).
