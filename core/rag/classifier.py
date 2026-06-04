"""Adaptive-RAG query classifier: a small LLM call that routes each query to a
retrieval tier.

  simple  -> answer directly, no retrieval
  medium  -> hybrid retrieve, take the fused top-k (no rerank)
  complex -> hybrid retrieve a larger candidate set, then rerank to top-k

Defensive: any failure / disabled flag falls back to "medium" (retrieve without
the extra rerank cost) rather than dropping retrieval entirely.
"""

import logging

from core.config import Settings
from core.llm.base import ChatService

log = logging.getLogger("rag.classifier")

SIMPLE, MEDIUM, COMPLEX = "simple", "medium", "complex"

_PROMPT = (
    "You route a user message to a retrieval strategy. Reply with EXACTLY one "
    "word — simple, medium, or complex:\n"
    "simple: chit-chat, or answerable from general knowledge or the ongoing "
    "conversation; no document lookup needed.\n"
    "medium: a factual question that likely needs looking something up in the "
    "knowledge base.\n"
    "complex: a multi-part, comparative, or nuanced question that needs careful "
    "ranking of several pieces of evidence.\n"
    "Answer with only one word."
)


class QueryClassifier:
    def __init__(self, chat_service: ChatService, settings: Settings) -> None:
        self._chat = chat_service
        self._settings = settings

    async def classify(self, query: str) -> str:
        if not self._settings.adaptive_classifier_enabled:
            return MEDIUM
        messages = [
            {"role": "system", "content": _PROMPT},
            {"role": "user", "content": query},
        ]
        try:
            out = (await self._chat.generate_reply("classify", messages)).strip().lower()
        except Exception:  # noqa: BLE001 — never let classification break a reply
            log.warning("query classification failed; defaulting to medium", exc_info=True)
            return MEDIUM
        # Order matters: check the most specific labels first.
        for tier in (COMPLEX, MEDIUM, SIMPLE):
            if tier in out:
                return tier
        return MEDIUM
