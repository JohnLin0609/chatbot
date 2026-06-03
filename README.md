# Simple Chatbot Backend

A minimal FastAPI backend that proxies chat messages to an LLM. The provider is
switchable via configuration between **Anthropic**, **OpenAI**, **Gemini**, and
**Ollama** (local).

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

cp .env.example .env
# edit .env and set ANTHROPIC_API_KEY
```

## Run

```bash
uvicorn app.main:app --reload
```

Open the interactive docs at http://localhost:8000/docs

## Endpoints

### `GET /health`

```bash
curl localhost:8000/health
# {"status":"ok"}
```

### `POST /chat`

```bash
curl -X POST localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{"session_id":"s1","message":"你好"}'
# {"session_id":"s1","reply":"..."}
```

`session_id` identifies a conversation. **Note:** conversation memory is not yet
implemented — each request is currently handled independently. `session_id` is
accepted now so that history can be added in the next stage without changing the
API contract (see the `TODO(next-stage)` in `app/chat_service.py`).

## Configuration

| Variable            | Default                  | Description                                   |
| ------------------- | ------------------------ | --------------------------------------------- |
| `PROVIDER`          | `anthropic`              | `anthropic` \| `openai` \| `gemini` \| `ollama` |
| `MODEL`             | _(per-provider default)_ | Model name; empty = provider default          |
| `ANTHROPIC_API_KEY` | —                        | Required when `PROVIDER=anthropic`            |
| `OPENAI_API_KEY`    | —                        | Required when `PROVIDER=openai`               |
| `GEMINI_API_KEY`    | —                        | Required when `PROVIDER=gemini`               |
| `OLLAMA_HOST`       | `http://localhost:11434` | Ollama server (no key needed)                 |
| `MAX_TOKENS`        | `1024`                   | Max tokens per reply                          |
| `SYSTEM_PROMPT`     | friendly assistant       | System prompt                                 |

Only the API key for the selected provider is required. Per-provider default
models:

| Provider    | Default model         |
| ----------- | --------------------- |
| `anthropic` | `claude-sonnet-4-6`   |
| `openai`    | `gpt-4o-mini`         |
| `gemini`    | `gemini-2.0-flash`    |
| `ollama`    | `llama3.2`            |

### Switching provider

Set `PROVIDER` (and the matching key) in `.env`, e.g. to use OpenAI:

```dotenv
PROVIDER=openai
OPENAI_API_KEY=sk-...
```

Or run Ollama locally with no key (`ollama serve` + `ollama pull llama3.2`):

```dotenv
PROVIDER=ollama
```
