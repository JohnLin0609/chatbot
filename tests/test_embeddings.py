"""EmbeddingService tests (OpenAI SDK mocked)."""

from unittest.mock import MagicMock

import openai
import pytest

from core.rag.embeddings import EmbeddingError, OpenAIEmbeddingService, build_embedding_service
from tests.conftest import make_settings


def _patch(monkeypatch, batches_seen):
    async def fake_create(model, input):
        batches_seen.append(input)
        # return one vector per input, contents echo the text length
        data = [type("D", (), {"embedding": [float(len(t))] * 3}) for t in input]
        return type("R", (), {"data": data})

    fake_client = MagicMock()
    fake_client.embeddings.create = fake_create
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: fake_client)


async def test_embed_preserves_order(monkeypatch):
    _patch(monkeypatch, [])
    svc = OpenAIEmbeddingService(make_settings())
    vecs = await svc.embed(["a", "bb", "ccc"])
    assert [v[0] for v in vecs] == [1.0, 2.0, 3.0]
    assert svc.dim == 1536


async def test_embed_batches(monkeypatch):
    seen = []
    _patch(monkeypatch, seen)
    svc = OpenAIEmbeddingService(make_settings(embedding_batch_size=2))
    await svc.embed(["a", "b", "c", "d", "e"])
    assert [len(b) for b in seen] == [2, 2, 1]


async def test_error_wrapped(monkeypatch):
    async def boom(model, input):
        raise openai.OpenAIError("down")

    fake_client = MagicMock()
    fake_client.embeddings.create = boom
    monkeypatch.setattr(openai, "AsyncOpenAI", lambda **kw: fake_client)
    svc = OpenAIEmbeddingService(make_settings())
    with pytest.raises(EmbeddingError):
        await svc.embed(["x"])


def test_build_unknown_provider():
    with pytest.raises(EmbeddingError):
        build_embedding_service(make_settings(embedding_provider="nope"))
