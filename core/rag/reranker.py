"""Cross-encoder reranking for the complex tier — local Qwen3-Reranker-0.6B.

The model scores each (query, document) pair via the yes/no token logits (per the
Qwen3-Reranker recipe). Loaded lazily; inference runs in a worker thread so it
never blocks the event loop. build_reranker() returns None when disabled or when
torch/transformers/the model are unavailable, in which case the complex tier
degrades to the fused top-k (same as medium).
"""

import asyncio
import logging
from typing import Protocol

from core.config import Settings
from core.rag.vector_store import Hit

log = logging.getLogger("rag.reranker")

_INSTRUCTION = (
    "Given a user question, judge whether the document is relevant and helpful "
    "for answering it."
)


class Reranker(Protocol):
    async def rerank(self, query: str, hits: list[Hit], top_k: int) -> list[Hit]: ...


class Qwen3Reranker:
    def __init__(self, model_name: str, device: str = "auto") -> None:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer

        self._torch = torch
        self._tok = AutoTokenizer.from_pretrained(model_name, padding_side="left")
        if self._tok.pad_token is None:
            self._tok.pad_token = self._tok.eos_token
        self._model = AutoModelForCausalLM.from_pretrained(model_name).eval()
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"
        self._device = device
        self._model.to(device)
        self._yes = self._tok.convert_tokens_to_ids("yes")
        self._no = self._tok.convert_tokens_to_ids("no")
        self._prefix = (
            '<|im_start|>system\nJudge whether the Document meets the requirements '
            'based on the Query and the Instruct provided. Note that the answer can '
            'only be "yes" or "no".<|im_end|>\n<|im_start|>user\n'
        )
        self._suffix = "<|im_end|>\n<|im_start|>assistant\n<think>\n\n</think>\n\n"

    def _format(self, query: str, doc: str) -> str:
        return (
            f"{self._prefix}<Instruct>: {_INSTRUCTION}\n<Query>: {query}\n"
            f"<Document>: {doc}{self._suffix}"
        )

    def _score(self, query: str, docs: list[str]) -> list[float]:
        torch = self._torch
        texts = [self._format(query, d) for d in docs]
        inputs = self._tok(
            texts, return_tensors="pt", padding=True, truncation=True, max_length=2048
        ).to(self._device)
        with torch.no_grad():
            last = self._model(**inputs).logits[:, -1, :]
            pair = last[:, [self._no, self._yes]]
            probs = torch.softmax(pair, dim=-1)[:, 1]
        return probs.tolist()

    async def rerank(self, query: str, hits: list[Hit], top_k: int) -> list[Hit]:
        if not hits:
            return []
        scores = await asyncio.to_thread(self._score, query, [h.text for h in hits])
        ranked = sorted(zip(hits, scores), key=lambda hs: hs[1], reverse=True)
        return [h for h, _ in ranked[:top_k]]


def build_reranker(settings: Settings) -> Reranker | None:
    if not settings.rag_reranker_enabled:
        return None
    try:
        return Qwen3Reranker(settings.rag_reranker_model, settings.rag_reranker_device)
    except Exception:  # noqa: BLE001 — optional; degrade to fused top-k
        log.warning(
            "reranker unavailable (%s); complex tier uses fused top-k",
            settings.rag_reranker_model,
            exc_info=True,
        )
        return None
