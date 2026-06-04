"""Parse .pptx into per-slide text. python-pptx is imported lazily so the module
is importable without the dependency installed."""

from dataclasses import dataclass


@dataclass
class SlideText:
    index: int  # 1-based slide number
    title: str
    body: str
    notes: str = ""


def parse_pptx(data: bytes) -> list[SlideText]:
    """Extract title / body / notes text per slide. Raises if python-pptx is
    missing or the bytes aren't a valid presentation."""
    from io import BytesIO

    from pptx import Presentation  # lazy: optional dependency

    prs = Presentation(BytesIO(data))
    slides: list[SlideText] = []
    for i, slide in enumerate(prs.slides, start=1):
        title_shape = slide.shapes.title
        title_id = title_shape.shape_id if title_shape is not None else None
        title = ""
        body_parts: list[str] = []
        for shape in slide.shapes:
            if not shape.has_text_frame:
                continue
            text = "\n".join(p.text for p in shape.text_frame.paragraphs).strip()
            if not text:
                continue
            if title_id is not None and shape.shape_id == title_id and not title:
                title = text
            else:
                body_parts.append(text)
        notes = ""
        if slide.has_notes_slide:
            notes = (slide.notes_slide.notes_text_frame.text or "").strip()
        slides.append(
            SlideText(index=i, title=title, body="\n".join(body_parts), notes=notes)
        )
    return slides
