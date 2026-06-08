"""Chunking-strategy tests. spaCy is not exercised here (model-free unit run);
the prose fallback path is tested by stubbing the nlp loader."""

import core.rag.chunkers as ck
from core.rag.chunkers import (
    ChunkUnit,
    _pack_sentences,
    chunk_code,
    chunk_prose,
    chunk_slides,
    chunk_token,
)
from core.rag.pptx import SlideText
from core.tokens.counter import TokenCounter
from tests.conftest import make_settings

C = TokenCounter()


def test_pack_sentences_groups_to_budget_with_overlap():
    sents = [f"sentence number {i} here." for i in range(6)]
    # budget fits ~2 sentences; overlap=1 means chunks share a boundary sentence.
    chunks = _pack_sentences(sents, C, budget=C.count_text(sents[0]) * 2, overlap=1)
    assert len(chunks) > 1
    # overlap: the last sentence of chunk k reappears at the start of chunk k+1
    first_tail = chunks[0].split(". ")[-1]
    assert first_tail and first_tail in chunks[1]


def test_pack_sentences_oversized_sentence_is_own_chunk():
    big = "word " * 100
    chunks = _pack_sentences(["tiny.", big, "end."], C, budget=5, overlap=1)
    assert any(big.strip() in c for c in chunks)
    assert len(chunks) >= 2  # always advances, never stalls


def test_chunk_token_wraps_chunk_text():
    text = " ".join(f"w{i}" for i in range(100))
    units = chunk_token(text, C, make_settings(ingest_chunk_tokens=20, ingest_chunk_overlap=4))
    assert len(units) > 1
    assert all(isinstance(u, ChunkUnit) for u in units)
    assert [u.ordinal for u in units] == list(range(len(units)))


def test_chunk_slides_one_per_slide_with_metadata():
    slides = [
        SlideText(index=1, title="Intro", body="hello world", notes=""),
        SlideText(index=2, title="", body="", notes=""),  # empty -> skipped
        SlideText(index=3, title="End", body="bye", notes="speaker note"),
    ]
    units = chunk_slides(slides, C, make_settings(ingest_chunk_tokens=512))
    assert len(units) == 2
    assert units[0].metadata["slide_number"] == 1
    assert units[0].metadata["title"] == "Intro"
    assert "speaker note" in units[1].text  # notes folded in


def test_chunk_slides_heading_leads_text_and_metadata_title():
    # the heading leads the chunk text (no deck prefix in the body) and is also
    # carried in metadata.title for citation/display.
    slides = [SlideText(index=1, title="錯誤的種類", body="語法錯誤與執行時例外")]
    units = chunk_slides(slides, C, make_settings(ingest_chunk_tokens=512))
    assert units[0].text == "錯誤的種類\n語法錯誤與執行時例外"
    assert units[0].metadata["title"] == "錯誤的種類"


def test_chunk_code_whole_file_one_chunk():
    code = 'def f():\n    return 1\n'
    units = chunk_code(code, C, make_settings(ingest_chunk_tokens=512))
    assert len(units) == 1 and units[0].text == code.rstrip()


def test_chunk_code_oversized_splits():
    code = "x = 1\n" * 200
    units = chunk_code(code, C, make_settings(ingest_chunk_tokens=20, ingest_chunk_overlap=4))
    assert len(units) > 1


def test_chunk_code_empty():
    assert chunk_code("   \n  ", C, make_settings()) == []


def test_chunk_slides_splits_oversized_slide():
    big = " ".join(f"w{i}" for i in range(300))
    slides = [SlideText(index=1, title="Big", body=big)]
    units = chunk_slides(slides, C, make_settings(ingest_chunk_tokens=20, ingest_chunk_overlap=4))
    assert len(units) > 1
    assert all(u.metadata["slide_number"] == 1 for u in units)


def test_chunk_prose_falls_back_to_token_when_no_spacy(monkeypatch):
    monkeypatch.setattr(ck, "_get_nlp", lambda model: None)
    text = " ".join(f"w{i}" for i in range(100))
    units = chunk_prose(text, C, make_settings(ingest_chunk_tokens=20, ingest_chunk_overlap=4))
    assert len(units) > 1  # token fallback produced multiple chunks


def test_chunk_prose_empty():
    assert chunk_prose("   ", C, make_settings()) == []
