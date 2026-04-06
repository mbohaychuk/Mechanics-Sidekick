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
the section exceeds chunk_size. The section title is carried on every chunk so it can
be prepended to embeddings and displayed to the chat LLM.
"""
from collections import Counter


_HEADING_EXCLUSION_PREFIXES = ("Fig.", "Courtesy of", "NOTE", "CAUTION", "WARNING")


class StructuredChunkingService:
    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 100) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def chunk_blocks(self, page_blocks: list[dict]) -> list[dict]:
        """Convert per-page block data into section-aware chunks.

        Args:
            page_blocks: Output of PDFService.extract_blocks() —
                         list of {"page_number": int, "blocks": list}

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
        """Walk all blocks and group text under detected section headings."""
        sections: list[dict] = []
        current_title = ""
        current_content: list[tuple[str, int]] = []  # (text, page_number)

        for page in page_blocks:
            page_num = page["page_number"]
            for block in page["blocks"]:
                for line in block["lines"]:
                    spans = [s for s in line["spans"] if s["text"].strip()]
                    if not spans:
                        continue

                    line_text = " ".join(s["text"] for s in spans).strip()
                    if not line_text:
                        continue

                    if self._is_heading(spans, body_size):
                        if current_content:
                            sections.append(
                                {"title": current_title, "content": current_content}
                            )
                        current_title = line_text
                        current_content = []
                    else:
                        current_content.append((line_text, page_num))

        if current_content:
            sections.append({"title": current_title, "content": current_content})

        return sections

    def _sections_to_chunks(self, sections: list[dict]) -> list[dict]:
        """Split each section into word-count windows, carrying the section title."""
        chunks: list[dict] = []
        chunk_index = 0
        stride = max(self._chunk_size - self._chunk_overlap, 1)

        for section in sections:
            words_with_pages: list[tuple[str, int]] = [
                (word, page_num)
                for text, page_num in section["content"]
                for word in text.split()
            ]
            if not words_with_pages:
                continue

            total = len(words_with_pages)
            start = 0
            while start < total:
                end = min(start + self._chunk_size, total)
                window = words_with_pages[start:end]
                chunks.append(
                    {
                        "chunk_index": chunk_index,
                        "page_number": window[0][1],
                        "section_title": section["title"],
                        "content": " ".join(w for w, _ in window),
                    }
                )
                chunk_index += 1
                start += stride

        return chunks
