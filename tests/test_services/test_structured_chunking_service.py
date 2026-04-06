# tests/test_services/test_structured_chunking_service.py
from app.services.structured_chunking_service import StructuredChunkingService


def _make_span(text, size=12.0, bold=False, font="Arial"):
    flags = 16 if bold else 0
    font_name = f"{font}-Bold" if bold else font
    return {"text": text, "size": size, "flags": flags, "font": font_name}


def _make_line(spans):
    return {"spans": spans}


def _make_block(lines):
    return {"type": 0, "lines": lines}


def _make_page(page_number, blocks):
    return {"page_number": page_number, "blocks": blocks}


def test_chunks_carry_section_title():
    svc = StructuredChunkingService(chunk_size=50, chunk_overlap=5)
    pages = [
        _make_page(1, [
            _make_block([_make_line([_make_span("TORQUE SPECIFICATIONS", size=12.0, bold=True)])]),
            _make_block([_make_line([_make_span("Tighten the bolt to 23 Nm in sequence as shown.", size=12.0)])]),
        ])
    ]
    chunks = svc.chunk_blocks(pages)
    assert len(chunks) >= 1
    assert chunks[0]["section_title"] == "TORQUE SPECIFICATIONS"


def test_figure_captions_not_treated_as_headings():
    svc = StructuredChunkingService(chunk_size=50, chunk_overlap=5)
    pages = [
        _make_page(1, [
            _make_block([_make_line([_make_span("Fig. 256: Cylinder Head Assembly Overview", size=12.0, bold=True)])]),
            _make_block([_make_line([_make_span("Body text below the figure.", size=12.0)])]),
        ])
    ]
    chunks = svc.chunk_blocks(pages)
    # Fig. line should not become a section heading — it stays as body content
    for chunk in chunks:
        assert chunk["section_title"] != "Fig. 256: Cylinder Head Assembly Overview"


def test_large_section_split_into_multiple_chunks():
    svc = StructuredChunkingService(chunk_size=5, chunk_overlap=1)
    words = " ".join(f"word{i}" for i in range(20))
    pages = [
        _make_page(1, [
            _make_block([_make_line([_make_span("CYLINDER HEAD", size=12.0, bold=True)])]),
            _make_block([_make_line([_make_span(words, size=12.0)])]),
        ])
    ]
    chunks = svc.chunk_blocks(pages)
    assert len(chunks) > 1
    assert all(c["section_title"] == "CYLINDER HEAD" for c in chunks)


def test_multiple_sections_produce_separate_titles():
    svc = StructuredChunkingService(chunk_size=50, chunk_overlap=5)
    pages = [
        _make_page(1, [
            _make_block([_make_line([_make_span("CYLINDER HEAD", size=12.0, bold=True)])]),
            _make_block([_make_line([_make_span("Head bolt torque is 23 Nm.", size=12.0)])]),
            _make_block([_make_line([_make_span("TORQUE CONVERTER", size=12.0, bold=True)])]),
            _make_block([_make_line([_make_span("Converter bolt torque is 45 Nm.", size=12.0)])]),
        ])
    ]
    chunks = svc.chunk_blocks(pages)
    titles = [c["section_title"] for c in chunks]
    assert "CYLINDER HEAD" in titles
    assert "TORQUE CONVERTER" in titles


def test_chunk_index_is_sequential():
    svc = StructuredChunkingService(chunk_size=50, chunk_overlap=5)
    pages = [
        _make_page(1, [
            _make_block([_make_line([_make_span("SECTION A", size=12.0, bold=True)])]),
            _make_block([_make_line([_make_span("Content for section A.", size=12.0)])]),
            _make_block([_make_line([_make_span("SECTION B", size=12.0, bold=True)])]),
            _make_block([_make_line([_make_span("Content for section B.", size=12.0)])]),
        ])
    ]
    chunks = svc.chunk_blocks(pages)
    indices = [c["chunk_index"] for c in chunks]
    assert indices == list(range(len(chunks)))


def test_empty_pages_returns_no_chunks():
    svc = StructuredChunkingService()
    assert svc.chunk_blocks([]) == []
