import logging
import re

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)

# Many service manuals are a concatenation of per-section documents, each introduced by a running
# header that names the section/variant (the Ford F-150 manual heads each with
# "Service Manual: ENGINE - 5.0L 32V TI-VCT"). That marker appears only on a section's first page, so
# we carry it forward to every following page. Stamping each chunk with it disambiguates otherwise
# identical spec tables across engine variants (5.0L oil capacity vs 2.7L). Tune per manual.
_DEFAULT_SECTION_HEADER_PATTERN = r"Service Manual:\s*(.+)"


class PDFService:
    def __init__(self, section_header_pattern: str = _DEFAULT_SECTION_HEADER_PATTERN) -> None:
        self._section_re = re.compile(section_header_pattern, re.IGNORECASE)

    def extract_pages(self, pdf_path: str) -> list[dict]:
        """Extract text page-by-page from a PDF.

        Returns list of {"page_number": int, "text": str}.
        Pages with no extractable text are omitted.
        """
        pages = []
        with fitz.open(pdf_path) as doc:
            for page_num, page in enumerate(doc, start=1):
                raw = page.get_text()
                normalized = " ".join(raw.split())
                if normalized:
                    pages.append({"page_number": page_num, "text": normalized})
        return pages

    def extract_blocks(self, pdf_path: str) -> list[dict]:
        """Extract rich block data page-by-page for structure-aware chunking.

        Returns list of {"page_number": int, "blocks": list, "tables": list, "section_context": str}.
        Each block is a PyMuPDF dict block with span-level font metadata. Each table is
        {"bbox": list[float]} — only its bounding box, used by the chunker to keep a table's text from
        being split across a chunk boundary. "section_context" is the carried-forward section/variant
        header (see the module note) so the chunker can label each chunk with which engine/system it
        belongs to. Pages with neither text blocks nor tables are omitted.
        """
        pages = []
        current_section = ""
        with fitz.open(pdf_path) as doc:
            for page_num, page in enumerate(doc, start=1):
                blocks = page.get_text("dict")["blocks"]
                text_blocks = [b for b in blocks if b["type"] == 0]
                tables = self._extract_table_regions(page)
                found = self._page_section(text_blocks)
                if found:
                    current_section = found
                if text_blocks or tables:
                    pages.append({
                        "page_number": page_num, "blocks": text_blocks,
                        "tables": tables, "section_context": current_section,
                    })
        return pages

    def _page_section(self, text_blocks: list[dict]) -> str:
        """Return this page's section header if it declares one (else "" — inherit the prior page's)."""
        for block in text_blocks:
            text = " ".join(s["text"] for line in block["lines"] for s in line["spans"])
            m = self._section_re.search(text)
            if m:
                return " ".join(m.group(1).split())
        return ""

    @staticmethod
    def _extract_table_regions(page) -> list[dict]:
        """Detect table bounding boxes with PyMuPDF's default ('lines') finder. The col>=2 / row>=2
        guard keeps false positives low. We only keep the bbox — the chunker uses it to avoid
        slicing a window through a table, so a spec value never gets cut from its column label."""
        try:
            found = page.find_tables()
        except Exception:
            logger.exception("table detection failed on page %s", getattr(page, "number", "?"))
            return []
        return [
            {"bbox": list(table.bbox)}
            for table in found.tables
            if table.col_count >= 2 and table.row_count >= 2
        ]
