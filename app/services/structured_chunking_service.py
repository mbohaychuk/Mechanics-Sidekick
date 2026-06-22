# app/services/structured_chunking_service.py
"""Structure-aware chunking that respects section boundaries detected from PDF font metadata.

Heading detection uses two portable heuristics that work across automotive technical
documentation formats (Audi, BMW, Mitchell, AllData, Haynes, etc.) without hardcoding
any document-specific strings:

  1. Bold + ALL_CAPS text → major section heading
  2. Bold + font size significantly larger than the document body → chapter/title heading

Figure captions ("Fig. ...") and attribution lines ("Courtesy of ...") are excluded
even though they are often bold, since they are not structural headings.

Within each detected section, text is split into overlapping word-count windows when
the section exceeds chunk_size. A table's text (located via PyMuPDF table bounding boxes)
is kept **atomic**: a window boundary is never allowed to fall inside a table, so a spec
value never gets cut from its column header. Tables ride inside the prose chunks — they are
not split into separate chunks, which would double the corpus and flood retrieval.
"""
from collections import Counter


_HEADING_EXCLUSION_PREFIXES = ("Fig.", "Courtesy of", "NOTE", "CAUTION", "WARNING")

# A table is kept whole only up to this multiple of chunk_size; a pathologically large table
# (a multi-page DTC chart) is split beyond it so a single chunk can't blow the embedding token limit.
_MAX_TABLE_CHUNK_FACTOR = 4


class StructuredChunkingService:
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 100) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def chunk_blocks(self, page_blocks: list[dict]) -> list[dict]:
        """Convert per-page block data into section-aware chunks.

        Args:
            page_blocks: Output of PDFService.extract_blocks() — list of
                         {"page_number": int, "blocks": list, "tables": list}.
                         "tables" is optional; each carries a "bbox" used only to keep the
                         table's text from being split across a chunk boundary.

        Returns:
            list of {"chunk_index", "page_number", "section_title", "content"}
        """
        body_size = self._detect_body_size(page_blocks)
        sections = self._split_into_sections(page_blocks, body_size)
        return self._sections_to_chunks(sections)

    # ── Private helpers ───────────────────────────────────────────────────────

    def _detect_body_size(self, page_blocks: list[dict]) -> float:
        """Return the most common font size across all spans — the body text size."""
        sizes = []
        for page in page_blocks:
            for block in page["blocks"]:
                for line in block["lines"]:
                    for span in line["spans"]:
                        if span["text"].strip():
                            sizes.append(round(span["size"], 1))
        if not sizes:
            return 12.0
        return Counter(sizes).most_common(1)[0][0]

    def _is_heading(self, spans: list[dict], body_size: float) -> bool:
        """Return True if this line's spans look like a structural section heading."""
        if not spans:
            return False

        line_text = " ".join(s["text"] for s in spans).strip()

        if len(line_text) < 4:
            return False
        if any(line_text.startswith(p) for p in _HEADING_EXCLUSION_PREFIXES):
            return False

        all_bold = all(
            (s.get("flags", 0) & 16) or ("Bold" in s.get("font", ""))
            for s in spans
        )
        if not all_bold:
            return False

        # ALL_CAPS line → major section heading (most reliable signal)
        stripped = line_text.replace(" ", "").replace("-", "").replace(",", "").replace(".", "")
        if stripped and stripped.isupper():
            return True

        # Font size distinctly different from body text → structural heading.
        # This catches both document titles (larger) and sub-section labels (smaller)
        # as seen in Audi/VW and similar OEM manual formats where sub-headings use
        # a smaller bold font than body text.
        avg_size = sum(s["size"] for s in spans) / len(spans)
        if abs(avg_size - body_size) > body_size * 0.05:
            return True

        return False

    def _split_into_sections(
        self, page_blocks: list[dict], body_size: float
    ) -> list[dict]:
        """Walk all blocks in PyMuPDF's native (column-aware) reading order, grouping text under
        detected section headings. Each content line is tagged with the table it belongs to (if any),
        so the windower below can keep that table's text together.

        Block and line order is never disturbed — PyMuPDF emits whole columns top-to-bottom, so
        re-sorting lines by y would scramble multi-column pages.
        """
        sections: list[dict] = []
        current_title = ""
        current_content: list[tuple[str, int, object]] = []  # (text, page_number, table_key)

        for page in page_blocks:
            page_num = page["page_number"]
            table_bboxes = [t["bbox"] for t in page.get("tables", []) if t.get("bbox")]
            for block in page["blocks"]:
                for line in block["lines"]:
                    spans = [s for s in line["spans"] if s["text"].strip()]
                    if not spans:
                        continue
                    line_text = " ".join(s["text"] for s in spans).strip()
                    if not line_text:
                        continue
                    table_key = self._line_table_key(line, page_num, table_bboxes)
                    # A bold cell inside a table is not a section heading — treating it as one would
                    # fragment the table. Only out-of-table lines are eligible to start a section.
                    if table_key is None and self._is_heading(spans, body_size):
                        if current_content:
                            sections.append({"title": current_title, "content": current_content})
                        current_title = line_text
                        current_content = []
                    else:
                        current_content.append((line_text, page_num, table_key))

        if current_content:
            sections.append({"title": current_title, "content": current_content})

        return sections

    @staticmethod
    def _line_table_key(line: dict, page_num: int, table_bboxes: list) -> object:
        """Return a stable key for the table containing this line (by bbox-center), else None."""
        bbox = line.get("bbox")
        if not bbox:
            return None
        cx, cy = (bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2
        for i, (tx0, ty0, tx1, ty1) in enumerate(table_bboxes):
            if tx0 <= cx <= tx1 and ty0 <= cy <= ty1:
                return (page_num, i)
        return None

    def _sections_to_chunks(self, sections: list[dict]) -> list[dict]:
        """Split each section into word-count windows, never cutting through a table."""
        chunks: list[dict] = []
        chunk_index = 0
        stride = max(self._chunk_size - self._chunk_overlap, 1)

        for section in sections:
            words: list[tuple[str, int, object]] = [
                (word, page_num, table_key)
                for text, page_num, table_key in section["content"]
                for word in text.split()
            ]
            total = len(words)
            if not total:
                continue

            max_chunk_words = self._chunk_size * _MAX_TABLE_CHUNK_FACTOR
            start = 0
            last_end = 0
            while start < total:
                end = self._snap_end_past_table(
                    words, min(start + self._chunk_size, total), total, start + max_chunk_words
                )
                if end <= last_end:
                    break  # a snapped table already pushed a prior window past here — nothing new
                window = words[start:end]
                # Cite the page contributing the most words to this chunk (tie -> earliest),
                # not the first word's page — otherwise a chunk that spans a page boundary
                # points at where it starts rather than where its content actually lives.
                page_counts = Counter(p for _, p, _ in window)
                page_number = min(page_counts, key=lambda p: (-page_counts[p], p))
                chunks.append(
                    {
                        "chunk_index": chunk_index,
                        "page_number": page_number,
                        "section_title": section["title"],
                        "content": " ".join(w for w, _, _ in window),
                    }
                )
                chunk_index += 1
                last_end = end
                # Advance by the stride, but never restart inside the table this window just
                # extended over (which would re-emit it many times for a large table).
                start = max(start + stride, end - self._chunk_overlap)

        return chunks

    @staticmethod
    def _snap_end_past_table(words: list[tuple], end: int, total: int, hard_cap: int) -> int:
        """Push a window's end forward so it never falls inside a table — if the words straddling
        the boundary share a table key, extend until the table ends, the section ends, or the
        per-chunk word cap is reached (so a giant table can't produce one over-limit chunk)."""
        while (
            end < total
            and end < hard_cap
            and words[end - 1][2] is not None
            and words[end][2] == words[end - 1][2]
        ):
            end += 1
        return end
