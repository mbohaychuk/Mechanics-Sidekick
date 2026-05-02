# app/services/table_chunker.py
"""Convert PyMuPDF table extractions into RAG chunks.

Each detected table produces:
  - one `table_whole` chunk: the full grid rendered as markdown — for queries
    that need cross-row context (e.g. "what bolts are listed for the head?")
  - one `table_row` chunk per data row, prefixed with the column headers — for
    spec-lookup queries that target a single value (e.g. "head bolt torque").

Both kinds share a stable `table_id` so a downstream component can fetch the
parent table when a row alone is ambiguous.
"""
import hashlib


class TableChunker:
    def chunk_tables(
        self,
        table_pages: list[dict],
        base_chunk_index: int,
        section_titles_by_page: dict[int, str],
    ) -> list[dict]:
        """Convert table data into chunks ready for embedding.

        Args:
            table_pages: Output of PDFService.extract_tables().
            base_chunk_index: Starting chunk_index — table chunks claim a
                contiguous block before prose chunking continues.
            section_titles_by_page: Map page_number -> nearest preceding
                section heading (computed by StructuredChunkingService).

        Returns:
            list of chunk dicts: chunk_index, page_number, section_title,
            content, chunk_kind, table_id, table_type=None (filled by
            MetadataExtractor in a later step).
        """
        chunks: list[dict] = []
        idx = base_chunk_index
        for page in table_pages:
            page_num = page["page_number"]
            section_title = section_titles_by_page.get(page_num)
            for tbl_pos, tbl in enumerate(page["tables"]):
                table_id = self._make_table_id(page_num, tbl_pos, tbl["rows"])
                header = tbl["header"] or [f"col_{i + 1}" for i in range(self._max_cols(tbl["rows"]))]

                # Whole-table chunk first.
                chunks.append({
                    "chunk_index": idx,
                    "page_number": page_num,
                    "section_title": section_title,
                    "content": self._render_markdown(header, tbl["rows"]),
                    "chunk_kind": "table_whole",
                    "table_id": table_id,
                    "table_type": None,
                })
                idx += 1

                # Per-row chunks (skip the header if it duplicates the explicit header).
                for row in tbl["rows"]:
                    if header and row == header:
                        continue
                    chunks.append({
                        "chunk_index": idx,
                        "page_number": page_num,
                        "section_title": section_title,
                        "content": self._render_row(header, row, section_title, table_id),
                        "chunk_kind": "table_row",
                        "table_id": table_id,
                        "table_type": None,
                    })
                    idx += 1
        return chunks

    def bboxes_by_page(self, table_pages: list[dict]) -> dict[int, list[tuple]]:
        """Return per-page list of table bboxes so prose chunking can exclude them."""
        return {
            page["page_number"]: [tbl["bbox"] for tbl in page["tables"]]
            for page in table_pages
        }

    # --- Private helpers -----------------------------------------------------

    @staticmethod
    def _max_cols(rows: list[list[str]]) -> int:
        return max((len(r) for r in rows), default=0)

    @staticmethod
    def _make_table_id(page_num: int, tbl_pos: int, rows: list[list[str]]) -> str:
        """Stable id keyed on page + position + first row contents."""
        first_row = "|".join(rows[0]) if rows else ""
        digest = hashlib.sha1(f"{page_num}:{tbl_pos}:{first_row}".encode()).hexdigest()[:12]
        return f"t_{digest}"

    @staticmethod
    def _render_markdown(header: list[str], rows: list[list[str]]) -> str:
        """Render the full table as a markdown grid for table_whole chunks."""
        lines = ["| " + " | ".join(header) + " |"]
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for row in rows:
            if row == header:
                continue
            padded = list(row) + [""] * (len(header) - len(row))
            lines.append("| " + " | ".join(padded) + " |")
        return "\n".join(lines)

    @staticmethod
    def _render_row(
        header: list[str],
        row: list[str],
        section_title: str | None,
        table_id: str,
    ) -> str:
        """Render a single row in a way that survives the embedder's lossy compression."""
        section_prefix = f"[Section: {section_title}] " if section_title else ""
        pairs = []
        for col, val in zip(header, row):
            if val:
                pairs.append(f"{col}: {val}")
        return f"{section_prefix}[Table {table_id}] " + " | ".join(pairs)
