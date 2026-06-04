# Backend image: one image, three roles (migrate / worker / api).
# The role is chosen by the `command:` in docker-compose.yml — nothing is baked
# in here. Heavy RAG deps (torch/transformers/spacy/fastembed) are included so the
# Qwen3 reranker + spaCy prose chunking work in-container; this makes the image
# multi-GB and the first build slow.
FROM python:3.12-slim

WORKDIR /app

# Some wheels (e.g. fastembed's onnxruntime, blis for spaCy) build from source on
# slim if no wheel matches; keep a minimal toolchain available, then prune apt.
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential \
    && rm -rf /var/lib/apt/lists/*

# CPU-only torch first, so the default CUDA wheel (multi-GB) is never pulled in by
# `-r requirements.txt`.
RUN pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Sentence model for prose chunking (falls back to token chunking if absent, but
# we want the real thing in the image).
RUN python -m spacy download xx_sent_ud_sm

# Application code (tests/docs/frontend are excluded via .dockerignore).
COPY core/ ./core/
COPY interfaces/ ./interfaces/
COPY shared/ ./shared/
COPY migrations/ ./migrations/
COPY alembic.ini ./alembic.ini

# Model weights (HF reranker ~1.2GB, fastembed BM25) cache here; mount a volume on
# this path in compose so they survive container recreates.
ENV HF_HOME=/root/.cache/huggingface

# No CMD: compose supplies the per-role command.
