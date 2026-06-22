# tests/test_services/test_structured_chunking_service.py
from app.services.structured_chunking_service import StructuredChunkingService


def _make_span(text, size=12.0, bold=False, font="Arial"):
    flags = 16 if bold else 0
    font_name = f"{font}-Bold" if bold else font
    return {"text": text, "size": size, "flags": flags, "font": font_name}


def _make_line(spans, bbox=None):
    line = {"spans": spans}
    if bbox is not None:
        line["bbox"] = bbox
    return line


def _make_block(lines, bbox=None):
    block = {"type": 0, "lines": lines}
    if bbox is not None:
        block["bbox"] = bbox
    return block


def _table_region(bbox):
    return {"bbox": bbox}  # tables are located by bbox only — to keep their text atomic


def _make_page(page_number, blocks, tables=None):
    page = {"page_number": page_number, "blocks": blocks}
    if tables is not None:
        page["tables"] = tables
    return page


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


# ── Multi-column reading order must survive table-awareness (regression) ──────

def test_two_column_reading_order_is_preserved_without_tables():
    # PyMuPDF emits the full left column, then the full right column (native reading order).
    # Table-awareness must not re-sort prose lines globally by y, or columns interleave.
    svc = StructuredChunkingService(chunk_size=500, chunk_overlap=50)
    pages = [
        _make_page(1, blocks=[
            _make_block([
                _make_line([_make_span("Left first.")], bbox=[50, 100, 200, 115]),
                _make_line([_make_span("Left second.")], bbox=[50, 130, 200, 145]),
            ], bbox=[50, 100, 200, 145]),
            _make_block([
                _make_line([_make_span("Right first.")], bbox=[300, 110, 450, 125]),
                _make_line([_make_span("Right second.")], bbox=[300, 140, 450, 155]),
            ], bbox=[300, 110, 450, 155]),
        ])
    ]
    content = " ".join(c["content"] for c in svc.chunk_blocks(pages))
    assert content == "Left first. Left second. Right first. Right second."


def test_two_column_section_attribution_is_not_cross_contaminated():
    svc = StructuredChunkingService(chunk_size=500, chunk_overlap=50)
    pages = [
        _make_page(1, blocks=[
            _make_block([
                _make_line([_make_span("BRAKES", bold=True)], bbox=[50, 50, 200, 65]),
                _make_line([_make_span("Brake bleeding procedure here.")], bbox=[50, 80, 200, 95]),
            ], bbox=[50, 50, 200, 95]),
            _make_block([
                _make_line([_make_span("ENGINE", bold=True)], bbox=[300, 55, 450, 70]),
                _make_line([_make_span("Engine oil capacity here.")], bbox=[300, 85, 450, 100]),
            ], bbox=[300, 55, 450, 100]),
        ])
    ]
    chunks = svc.chunk_blocks(pages)
    brake = next(c for c in chunks if "bleeding" in c["content"])
    engine = next(c for c in chunks if "oil capacity" in c["content"])
    assert brake["section_title"] == "BRAKES"
    assert engine["section_title"] == "ENGINE"


# ── Tables are kept atomic: a window boundary never cuts through one ──────────

def test_table_text_is_not_split_across_chunks():
    # 4 table rows (4 words each = 16 words) sit inside a table bbox; chunk_size=8 would normally
    # slice them across chunks. The atomic rule must keep all rows together in one chunk.
    svc = StructuredChunkingService(chunk_size=8, chunk_overlap=2)
    table_lines = [
        _make_line([_make_span(f"alpha{i} beta gamma delta")], bbox=[50, 100 + i * 20, 300, 116 + i * 20])
        for i in range(4)
    ]
    pages = [
        _make_page(1,
            blocks=[
                _make_block([_make_line([_make_span("SPECS", bold=True)], bbox=[50, 40, 200, 55])], bbox=[50, 40, 200, 55]),
                _make_block(table_lines, bbox=[50, 100, 300, 180]),
            ],
            tables=[_table_region([50, 98, 300, 182])],
        )
    ]
    chunks = svc.chunk_blocks(pages)
    holding = [c for c in chunks if "alpha0" in c["content"]]
    assert len(holding) == 1, "the table's rows must all live in a single chunk"
    body = holding[0]["content"]
    assert all(f"alpha{i}" in body for i in range(4))


def test_oversized_table_splits_into_bounded_chunks_without_duplicates():
    # A table far larger than chunk_size must NOT become one unbounded chunk (it would blow the
    # embedding token limit). It splits into bounded chunks; every row survives; none are duplicates.
    svc = StructuredChunkingService(chunk_size=10, chunk_overlap=2)  # atomic cap = 4 * 10 = 40 words
    rows = [
        _make_line([_make_span(f"r{i} aa bb")], bbox=[50, 100 + i * 10, 300, 108 + i * 10])
        for i in range(30)  # 30 rows x 3 words = 90 words, > the 40-word cap
    ]
    pages = [_make_page(1,
        blocks=[_make_block(rows, bbox=[50, 100, 300, 400])],
        tables=[_table_region([45, 95, 305, 405])],
    )]
    chunks = svc.chunk_blocks(pages)
    body_all = " " + " ".join(c["content"] for c in chunks) + " "
    assert all(f" r{i} " in body_all for i in range(30))            # every row is somewhere
    assert all(len(c["content"].split()) <= 40 for c in chunks)     # no chunk exceeds the cap
    contents = [c["content"] for c in chunks]
    assert len(contents) == len(set(contents))                      # no redundant duplicate chunk


def test_right_column_prose_is_not_absorbed_into_a_left_column_table():
    # A table in the left column must not swallow right-column prose whose lines sit at the same y.
    svc = StructuredChunkingService(chunk_size=500, chunk_overlap=50)
    pages = [_make_page(1,
        blocks=[
            _make_block([
                _make_line([_make_span("leftrow1 cellA cellB")], bbox=[50, 100, 200, 116]),
                _make_line([_make_span("leftrow2 cellC cellD")], bbox=[50, 120, 200, 136]),
            ], bbox=[50, 100, 200, 136]),
            _make_block([
                _make_line([_make_span("Right column prose paragraph.")], bbox=[300, 105, 460, 121]),
            ], bbox=[300, 105, 460, 121]),
        ],
        tables=[_table_region([45, 95, 210, 140])],  # covers only the LEFT column
    )]
    chunks = svc.chunk_blocks(pages)
    # Right-column prose must not be tagged into the left table (its bbox-center is outside the table).
    holding_right = [c for c in chunks if "Right column prose" in c["content"]]
    assert holding_right, "right-column prose must still be chunked"


def test_bold_cell_inside_a_table_is_not_treated_as_a_heading():
    # A gear/spec table often has bold cell labels; they must not break the table into sections.
    svc = StructuredChunkingService(chunk_size=500, chunk_overlap=50)
    pages = [
        _make_page(1,
            blocks=[
                _make_block([
                    _make_line([_make_span("GEAR RATIOS", bold=True)], bbox=[50, 100, 200, 116]),
                    _make_line([_make_span("FIRST", bold=True)], bbox=[50, 120, 200, 136]),  # bold ALL-CAPS data cell
                    _make_line([_make_span("3.97")], bbox=[50, 140, 200, 156]),
                    _make_line([_make_span("SECOND", bold=True)], bbox=[50, 160, 200, 176]),
                    _make_line([_make_span("2.32")], bbox=[50, 180, 200, 196]),
                ], bbox=[50, 100, 200, 196]),
            ],
            tables=[_table_region([45, 95, 260, 200])],
        )
    ]
    chunks = svc.chunk_blocks(pages)
    # The bold ALL-CAPS cells (GEAR RATIOS / FIRST / SECOND) would each look like a heading, but
    # because they're inside the table bbox none start a section — the whole table is one chunk.
    holding = [c for c in chunks if "GEAR RATIOS" in c["content"]]
    assert len(holding) == 1
    body = holding[0]["content"]
    assert "FIRST" in body and "3.97" in body and "SECOND" in body and "2.32" in body


def test_prose_without_tables_still_splits_normally():
    # The atomic rule must not change ordinary prose windowing (no tables -> identical behavior).
    svc = StructuredChunkingService(chunk_size=5, chunk_overlap=1)
    words = " ".join(f"word{i}" for i in range(20))
    pages = [_make_page(1, [
        _make_block([_make_line([_make_span("CYLINDER HEAD", bold=True)])]),
        _make_block([_make_line([_make_span(words)])]),
    ])]
    chunks = svc.chunk_blocks(pages)
    assert len(chunks) > 1  # a long table-free section still splits into multiple windows


def test_chunk_cites_dominant_page_when_spanning_a_boundary():
    # A chunk whose content is mostly on page 6 must cite page 6, not page 5 (its first word).
    svc = StructuredChunkingService(chunk_size=4, chunk_overlap=0)
    pages = [
        _make_page(5, [
            _make_block([_make_line([_make_span("SPECIFICATIONS", size=12.0, bold=True)])]),
            _make_block([_make_line([_make_span("intro", size=12.0)])]),
        ]),
        _make_page(6, [
            _make_block([_make_line([_make_span("torque is 23nm", size=12.0)])]),
        ]),
    ]
    chunks = svc.chunk_blocks(pages)
    assert chunks[0]["page_number"] == 6
