"""Chunking tests."""

from core.rag.chunking import chunk_text
from core.tokens.counter import TokenCounter

C = TokenCounter()


def test_empty_text():
    assert chunk_text(C, "", 100, 10) == []
    assert chunk_text(C, "   ", 100, 10) == []


def test_short_text_single_chunk():
    assert chunk_text(C, "hello world", 100, 10) == ["hello world"]


def test_long_text_multiple_chunks():
    text = " ".join(f"word{i}" for i in range(200))
    chunks = chunk_text(C, text, chunk_tokens=50, overlap=10)
    assert len(chunks) > 1
    # each chunk within budget
    for c in chunks:
        assert C.count_text(c) <= 50 + 5  # small slack for decode boundaries


def test_overlap_guard_does_not_hang():
    text = " ".join(f"w{i}" for i in range(100))
    # overlap >= chunk_tokens would stall; guard halves it
    chunks = chunk_text(C, text, chunk_tokens=20, overlap=20)
    assert len(chunks) > 1


def test_covers_all_content():
    text = " ".join(f"token{i}" for i in range(120))
    chunks = chunk_text(C, text, chunk_tokens=40, overlap=8)
    joined = " ".join(chunks)
    # first and last tokens present somewhere
    assert "token0" in joined and "token119" in joined
