import fitz
import pytest
from pathlib import Path
from app.services.pdf_service import PDFService


@pytest.fixture
def sample_pdf(tmp_path) -> Path:
    pdf_path = tmp_path / "test.pdf"
    doc = fitz.open()
    page1 = doc.new_page()
    page1.insert_text((72, 72), "Front caliper bracket bolt torque: 129 Nm")
    page2 = doc.new_page()
    page2.insert_text((72, 72), "Minimum rotor thickness: 20mm")
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_extract_pages_returns_page_list(sample_pdf):
    svc = PDFService()
    pages = svc.extract_pages(str(sample_pdf))
    assert len(pages) == 2
    assert pages[0]["page_number"] == 1
    assert "129" in pages[0]["text"]
    assert pages[1]["page_number"] == 2
    assert "20mm" in pages[1]["text"]


def test_extract_pages_skips_empty_pages(tmp_path):
    pdf_path = tmp_path / "empty.pdf"
    doc = fitz.open()
    doc.new_page()  # blank page — no text
    doc.save(str(pdf_path))
    doc.close()

    svc = PDFService()
    pages = svc.extract_pages(str(pdf_path))
    assert pages == []


def _draw_table(page, header, rows, x0=60, top=80, col_w=170, dy=24):
    """Draw a bordered table (vector gridlines + cell text) that find_tables() detects reliably."""
    grid = [header, *rows]
    n_cols = len(header)
    xs = [x0 + i * col_w for i in range(n_cols + 1)]
    bottom = top + dy * len(grid)
    for x in xs:
        page.draw_line((x, top), (x, bottom))
    y = top
    for _ in range(len(grid) + 1):
        page.draw_line((xs[0], y), (xs[-1], y))
        y += dy
    for r, cells in enumerate(grid):
        for c, cell in enumerate(cells):
            page.insert_text((xs[c] + 4, top + dy * r + 16), str(cell), fontsize=11)


@pytest.fixture
def table_pdf(tmp_path) -> Path:
    pdf_path = tmp_path / "table.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((60, 50), "TORQUE SPECIFICATIONS", fontsize=14)
    _draw_table(
        page,
        header=["Fastener", "Torque (lb-ft)"],
        rows=[["Oil drain plug", "18"], ["Spark plug", "11"], ["Wheel lug nut", "150"]],
    )
    doc.save(str(pdf_path))
    doc.close()
    return pdf_path


def test_extract_blocks_detects_table_region(table_pdf):
    svc = PDFService()
    pages = svc.extract_blocks(str(table_pdf))
    assert len(pages) == 1
    tables = pages[0]["tables"]
    assert len(tables) == 1
    assert len(tables[0]["bbox"]) == 4  # a bounding box, nothing more


def test_extract_blocks_keeps_table_text_inline(table_pdf):
    svc = PDFService()
    pages = svc.extract_blocks(str(table_pdf))
    block_text = " ".join(
        s["text"]
        for b in pages[0]["blocks"]
        for line in b["lines"]
        for s in line["spans"]
    )
    # Both the heading and the cell text stay as normal text blocks — the table is kept inline,
    # not extracted out. The bbox (above) is used only to keep that text from being split.
    assert "TORQUE SPECIFICATIONS" in block_text
    assert "Oil drain plug" in block_text
    assert "Wheel lug nut" in block_text


def test_extract_blocks_no_tables_on_plain_page(sample_pdf):
    svc = PDFService()
    pages = svc.extract_blocks(str(sample_pdf))
    assert pages
    assert all(page["tables"] == [] for page in pages)


@pytest.fixture
def multi_section_pdf(tmp_path) -> Path:
    # Mimics a manual concatenated from per-section documents: a "Service Manual: <section>" marker
    # appears only on each section's first page; continuation pages have none.
    path = tmp_path / "multi.pdf"
    doc = fitz.open()
    p1 = doc.new_page(); p1.insert_text((50, 40), "Service Manual: ENGINE - 5.0L"); p1.insert_text((50, 110), "Oil capacity 7.75 qt")
    p2 = doc.new_page(); p2.insert_text((50, 110), "Cylinder head bolt torque 75 Nm")  # continuation, no marker
    p3 = doc.new_page(); p3.insert_text((50, 40), "Service Manual: ENGINE - 2.7L"); p3.insert_text((50, 110), "Oil capacity 6.0 qt")
    doc.save(str(path)); doc.close()
    return path


def test_extract_blocks_carries_section_context_forward(multi_section_pdf):
    pages = PDFService().extract_blocks(str(multi_section_pdf))
    ctx = {p["page_number"]: p["section_context"] for p in pages}
    assert ctx[1] == "ENGINE - 5.0L"
    assert ctx[2] == "ENGINE - 5.0L"   # inherited — no marker on the continuation page
    assert ctx[3] == "ENGINE - 2.7L"   # a new section marker resets it


def test_table_detection_failure_is_logged_not_silent(monkeypatch, sample_pdf, caplog):
    import logging

    def boom(*a, **k):
        raise RuntimeError("detector exploded")

    monkeypatch.setattr(fitz.Page, "find_tables", boom, raising=True)
    svc = PDFService()
    with caplog.at_level(logging.ERROR):
        pages = svc.extract_blocks(str(sample_pdf))
    # Degrades to no tables, but leaves a trace rather than swallowing silently.
    assert all(p["tables"] == [] for p in pages)
    assert any("table" in r.message.lower() for r in caplog.records)
