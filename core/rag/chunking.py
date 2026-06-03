"""Token-based text chunking for ingestion."""

from core.tokens.counter import TokenCounter


def chunk_text(
    counter: TokenCounter, text: str, chunk_tokens: int, overlap: int
) -> list[str]:
    """Split text into overlapping token windows, decoded back to strings.

    Returns [] for empty text. A text shorter than chunk_tokens yields one chunk.
    """
    text = text.strip()
    if not text:
        return []
    if overlap >= chunk_tokens:
        overlap = chunk_tokens // 2  # guard against non-advancing windows

    tokens = counter.encode(text)
    if len(tokens) <= chunk_tokens:
        return [text]

    chunks: list[str] = []
    step = chunk_tokens - overlap
    for start in range(0, len(tokens), step):
        window = tokens[start : start + chunk_tokens]
        if not window:
            break
        chunks.append(counter.decode(window).strip())
        if start + chunk_tokens >= len(tokens):
            break
    return [c for c in chunks if c]
