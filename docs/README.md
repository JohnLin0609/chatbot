# Documentation

A layered, async chatbot **control console**: a platform-agnostic **core** owns
conversation behaviour (four memory tiers + Adaptive-RAG/tools) and talks to a
switchable LLM; **adapters** (unified JWT API, CLI, Discord) connect front-ends
over Redis Streams; a React SPA (`frontend/`) provides chat + admin. Durable state
lives in PostgreSQL + Qdrant, hot context in Redis.

## Documents

| Doc | Purpose |
| --- | --- |
| [architecture.md](architecture.md) | Technical reference: layers, message flow, memory tiers, RAG/tools. |
| [progress.md](progress.md) | What's built so far, test inventory, known limitations, live-verified behaviour. |
| [development.md](development.md) | Local setup, running services & tests, and how to extend (tools / providers / migrations / config). |
| [deployment.md](deployment.md) | Deploying to another machine: services, secrets, migrations, process model, scaling. |
| [roadmap.md](roadmap.md) | Planned-but-unbuilt features and the extension points already in place for each. |
| [decisions.md](decisions.md) | Design decisions and the rationale behind them ("why"). |

## TL;DR run

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements-dev.txt
cp .env.example .env            # set OPENAI_API_KEY
docker compose up -d            # redis (6380) + postgres (5434) + qdrant (6333)
alembic upgrade head
# then, in separate terminals:
python -m interfaces.worker                  # core worker + idle-session sweeper
uvicorn interfaces.api_app:app --port 8753   # unified JWT API (/auth, /chat, admin docs)
cd frontend && npm install && npm run dev    # web console (http://localhost:5173)
```

See [development.md](development.md) for the full guide.
