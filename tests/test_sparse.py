"""BM25 tokenisation (jieba). The fastembed model itself is exercised in the
integration test, not here."""

from core.rag.sparse import tokenize_for_bm25


def test_tokenize_segments_chinese():
    out = tokenize_for_bm25("我想要退款")
    # jieba splits Chinese into words separated by spaces
    assert " " in out
    assert "我" in out or "想要" in out or "退款" in out


def test_tokenize_keeps_latin_and_mixes():
    out = tokenize_for_bm25("refund 退款 policy")
    toks = out.split()
    assert "refund" in toks and "policy" in toks
    assert any("退" in t for t in toks)


def test_tokenize_blank():
    assert tokenize_for_bm25("   ") == ""
