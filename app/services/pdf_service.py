import fitz  # PyMuPDF


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

        Returns list of {"page_number": int, "blocks": list}.
        Each block is a PyMuPDF dict block with span-level font metadata.
        Pages with no text blocks are omitted.
        """
        pages = []
        with fitz.open(pdf_path) as doc:
            for page_num, page in enumerate(doc, start=1):
                blocks = page.get_text("dict")["blocks"]
                text_blocks = [b for b in blocks if b["type"] == 0]
                if text_blocks:
                    pages.append({"page_number": page_num, "blocks": text_blocks})
        return pages

    def extract_tables(self, pdf_path: str) -> list[dict]:
        """Detect tables page-by-page via PyMuPDF.

        Returns list of {"page_number": int, "tables": list[dict]}.
        Each table dict: {"bbox": (x0, y0, x1, y1), "header": list[str] | None, "rows": list[list[str]]}.
        Pages with no detected tables are omitted.
        """
        pages = []
        with fitz.open(pdf_path) as doc:
            for page_num, page in enumerate(doc, start=1):
                finder = page.find_tables()
                if not finder.tables:
                    continue
                page_tables = []
                for tbl in finder.tables:
                    rows = tbl.extract()  # list[list[str | None]]
                    rows = [[(c or "").strip() for c in row] for row in rows]
                    header = tbl.header.names if tbl.header and not tbl.header.external else None
                    page_tables.append({
                        "bbox": tuple(tbl.bbox),
                        "header": header,
                        "rows": rows,
                    })
                pages.append({"page_number": page_num, "tables": page_tables})
        return pages
