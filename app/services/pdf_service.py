import logging

import fitz  # PyMuPDF

logger = logging.getLogger(__name__)


class PDFService:
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

        Returns list of {"page_number": int, "blocks": list, "tables": list}. Each block is a
        PyMuPDF dict block with span-level font metadata. Each table is {"bbox": list[float]} — only
        its bounding box, used by the chunker to keep a table's text from being split across a chunk
        boundary. The table's text is NOT extracted or removed; it stays inline in the text blocks.
        Pages with neither text blocks nor tables are omitted.
        """
        pages = []
        with fitz.open(pdf_path) as doc:
            for page_num, page in enumerate(doc, start=1):
                blocks = page.get_text("dict")["blocks"]
                text_blocks = [b for b in blocks if b["type"] == 0]
                tables = self._extract_table_regions(page)
                if text_blocks or tables:
                    pages.append(
                        {"page_number": page_num, "blocks": text_blocks, "tables": tables}
                    )
        return pages

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
