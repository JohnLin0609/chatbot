"""parse_pptx: build a tiny presentation in-memory and parse it back."""

from io import BytesIO

from core.rag.pptx import parse_pptx


def _build_pptx() -> bytes:
    from pptx import Presentation

    prs = Presentation()
    layout = prs.slide_layouts[1]  # Title + Content

    s1 = prs.slides.add_slide(layout)
    s1.shapes.title.text = "First Slide"
    s1.placeholders[1].text = "Body of the first slide"

    s2 = prs.slides.add_slide(layout)
    s2.shapes.title.text = "Second Slide"
    s2.placeholders[1].text = "More content here"

    buf = BytesIO()
    prs.save(buf)
    return buf.getvalue()


def test_parse_pptx_per_slide():
    slides = parse_pptx(_build_pptx())
    assert len(slides) == 2
    assert slides[0].index == 1
    assert slides[0].title == "First Slide"
    assert "first slide" in slides[0].body.lower()
    assert slides[1].title == "Second Slide"
