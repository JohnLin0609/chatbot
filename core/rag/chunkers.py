"""Per-type chunking strategies.

A document's `doc_type` selects how it's split:
  - "slides" : one chunk per slide (split a slide that exceeds the token budget)
  - "prose"  : spaCy sentence segmentation, greedily packed to the token budget
               with N-sentence overlap (preserves semantic boundaries)
  - "token"  : fixed token windows (the original behaviour / fallback)

spaCy is loaded lazily and the prose strategy falls back to token windows if
spaCy or its model is unavailable, so the feature is optional.
"""

import logging
from dataclasses import dataclass, field

from core.config import Settings
from core.rag.chunking import chunk_text
from core.rag.pptx import SlideText
from core.tokens.counter import TokenCounter

log = logging.getLogger("rag.chunkers")

_NLP_CACHE: dict[str, object] = {}
_NLP_FAILED: set[str] = set()


@dataclass
class ChunkUnit:
    text: str
    ordinal: int
    metadata: dict = field(default_factory=dict)


def _get_nlp(model: str):
    """Lazy-load a spaCy pipeline; cache it; return None if unavailable."""
    if model in _NLP_CACHE:
        return _NLP_CACHE[model]
    if model in _NLP_FAILED:
        return None
    try:
        import spacy

        nlp = spacy.load(model, exclude=["ner", "lemmatizer", "tagger", "parser"])
        if "senter" not in nlp.pipe_names and "sentencizer" not in nlp.pipe_names:
            nlp.add_pipe("sentencizer")
    except Exception:  # noqa: BLE001 — optional; fall back to token chunking
        log.warning("spaCy model %r unavailable; prose falls back to token chunks", model)
        _NLP_FAILED.add(model)
        return None
    _NLP_CACHE[model] = nlp
    return nlp


def _pack_sentences(
    sents: list[str], counter: TokenCounter, budget: int, overlap: int
) -> list[str]:
    """Greedily pack sentences up to `budget` tokens, carrying `overlap`
    sentences into the next chunk. Always advances (a lone over-budget sentence
    becomes its own chunk)."""
    chunks: list[str] = []
    i, n = 0, len(sents)
    while i < n:
        cur: list[str] = []
        tok = 0
        j = i
        while j < n:
            st = counter.count_text(sents[j])
            if cur and tok + st > budget:
                break
            cur.append(sents[j])
            tok += st
            j += 1
        chunks.append(" ".join(cur))
        if j >= n:
            break
        i = max(j - overlap, i + 1)
    return chunks


def chunk_prose(text: str, counter: TokenCounter, settings: Settings) -> list[ChunkUnit]:
    text = text.strip()
    if not text:
        return []
    nlp = _get_nlp(settings.spacy_model)
    if nlp is None:
        return chunk_token(text, counter, settings)
    sents = [s.text.strip() for s in nlp(text).sents if s.text.strip()]
    if not sents:
        return chunk_token(text, counter, settings)
    packed = _pack_sentences(
        sents, counter, settings.ingest_chunk_tokens, settings.chunk_sentence_overlap
    )
    return [ChunkUnit(text=c, ordinal=i) for i, c in enumerate(packed) if c]


def chunk_token(text: str, counter: TokenCounter, settings: Settings) -> list[ChunkUnit]:
    pieces = chunk_text(
        counter, text, settings.ingest_chunk_tokens, settings.ingest_chunk_overlap
    )
    return [ChunkUnit(text=c, ordinal=i) for i, c in enumerate(pieces)]


def chunk_code(text: str, counter: TokenCounter, settings: Settings) -> list[ChunkUnit]:
    """One chunk for the whole code file (a small self-contained example), so the
    LLM sees a runnable unit. Falls back to token windows only if over budget."""
    text = text.rstrip()
    if not text.strip():
        return []
    if counter.count_text(text) <= settings.ingest_chunk_tokens:
        return [ChunkUnit(text=text, ordinal=0)]
    return chunk_token(text, counter, settings)


def chunk_slides(
    slides: list[SlideText], counter: TokenCounter, settings: Settings
) -> list[ChunkUnit]:
    """One chunk per slide; a slide over the token budget is split further.

    The slide heading (now reliably populated by parse_pptx, even when the deck
    doesn't use a title placeholder) leads the chunk text and is also kept in
    `metadata.title` so retrieval/citation can name the slide. The deck/week is
    surfaced at injection time via the citation label, not embedded into the
    chunk text (an A/B showed a constant per-deck prefix slightly hurts
    retrieval without adding signal the cited source doesn't already carry).
    """
    units: list[ChunkUnit] = []
    ordinal = 0
    for sl in slides:
        parts = [p for p in (sl.title, sl.body, sl.notes) if p and p.strip()]
        text = "\n".join(parts).strip()
        if not text:
            continue
        meta = {"slide_number": sl.index, "title": sl.title or None}
        if counter.count_text(text) <= settings.ingest_chunk_tokens:
            units.append(ChunkUnit(text=text, ordinal=ordinal, metadata=meta))
            ordinal += 1
        else:
            for piece in chunk_text(
                counter, text, settings.ingest_chunk_tokens, settings.ingest_chunk_overlap
            ):
                units.append(ChunkUnit(text=piece, ordinal=ordinal, metadata=dict(meta)))
                ordinal += 1
    return units


# Text-input strategies, keyed by doc_type. ("slides" takes structured input and
# is dispatched separately by IngestService.)
TEXT_STRATEGIES = {
    "prose": chunk_prose,
    "token": chunk_token,
}


def chunk_text_doc(
    doc_type: str, text: str, counter: TokenCounter, settings: Settings
) -> list[ChunkUnit]:
    strategy = TEXT_STRATEGIES.get(doc_type, chunk_prose)
    return strategy(text, counter, settings)
