# Documentation

A layered, async chatbot backend: a platform-agnostic **core** owns conversation
behaviour (four memory tiers + tool-calling/RAG) and talks to a switchable LLM;
thin **adapters** connect front-ends over Redis Streams. Durable state lives in
PostgreSQL, hot context in Redis, and curated knowledge vectors in Qdrant.

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
python -m interfaces.worker                  # core worker
uvicorn interfaces.http_app:app --port 8753  # chat gateway
uvicorn interfaces.admin_app:app --port 8754 # knowledge ingest
```

See [development.md](development.md) for the full guide.
