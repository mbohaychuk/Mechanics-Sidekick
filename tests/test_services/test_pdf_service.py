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


def test_extract_tables_returns_per_page_table_data(tmp_path):
    """Smoke test: a PDF with a clear grid table → extract_tables yields rows + bbox."""
    import fitz
    pdf_path = tmp_path / "table.pdf"
    doc = fitz.open()
    page = doc.new_page()
    # Draw a 2x2 grid with text in cells.
    page.draw_rect(fitz.Rect(50, 50, 250, 150))
    page.draw_line(fitz.Point(50, 100), fitz.Point(250, 100))
    page.draw_line(fitz.Point(150, 50), fitz.Point(150, 150))
    page.insert_text(fitz.Point(60, 70), "Spec")
    page.insert_text(fitz.Point(160, 70), "Value")
    page.insert_text(fitz.Point(60, 120), "Torque")
    page.insert_text(fitz.Point(160, 120), "129 Nm")
    doc.save(str(pdf_path))
    doc.close()

    from app.services.pdf_service import PDFService
    pages = PDFService().extract_tables(str(pdf_path))

    assert len(pages) == 1
    assert pages[0]["page_number"] == 1
    assert len(pages[0]["tables"]) >= 1
    table = pages[0]["tables"][0]
    assert "rows" in table         # list[list[str]]
    assert "bbox" in table         # tuple[float, float, float, float]
    assert "header" in table       # list[str] | None
