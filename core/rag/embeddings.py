"""Embedding abstraction. The model is fixed for the whole vector collection,
independent of the chat `provider`."""

from abc import ABC, abstractmethod

from core.config import Settings


class EmbeddingError(Exception):
    """Raised when the embedding backend fails."""


class EmbeddingService(ABC):
    @property
    @abstractmethod
    def dim(self) -> int: ...

    @abstractmethod
    async def embed(self, texts: list[str]) -> list[list[float]]:
        """Embed texts, preserving order. Batches internally if needed."""


class OpenAIEmbeddingService(EmbeddingService):
    def __init__(self, settings: Settings) -> None:
        from openai import AsyncOpenAI

        from core.llm.base import _require

        self._client = AsyncOpenAI(
            api_key=_require(settings.openai_api_key, "OPENAI_API_KEY")
        )
        self._model = settings.embedding_model
        self._dim = settings.embedding_dim
        self._batch = settings.embedding_batch_size

    @property
    def dim(self) -> int:
        return self._dim

    async def embed(self, texts: list[str]) -> list[list[float]]:
        from openai import OpenAIError

        out: list[list[float]] = []
        for i in range(0, len(texts), self._batch):
            batch = texts[i : i + self._batch]
            try:
                resp = await self._client.embeddings.create(
                    model=self._model, input=batch
                )
            except OpenAIError as exc:
                raise EmbeddingError(str(exc)) from exc
            out.extend(d.embedding for d in resp.data)
        return out


def build_embedding_service(settings: Settings) -> EmbeddingService:
    if settings.embedding_provider == "openai":
        return OpenAIEmbeddingService(settings)
    raise EmbeddingError(
        f"unsupported embedding provider: {settings.embedding_provider}"
    )
