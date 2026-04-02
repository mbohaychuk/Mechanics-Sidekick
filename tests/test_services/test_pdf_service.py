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
