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
