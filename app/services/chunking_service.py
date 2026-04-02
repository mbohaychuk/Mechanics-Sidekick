class ChunkingService:
    def __init__(self, chunk_size: int = 1000, chunk_overlap: int = 200) -> None:
        self._chunk_size = chunk_size
        self._chunk_overlap = chunk_overlap

    def chunk_pages(self, pages: list[dict]) -> list[dict]:
        """Split page-extracted text into overlapping word-based chunks.

        Page number recorded per chunk is that of the first word in the chunk.
        """
        if not pages:
            return []

        words_with_pages: list[tuple[str, int]] = [
            (word, page["page_number"])
            for page in pages
            for word in page["text"].split()
        ]

        total = len(words_with_pages)
        chunks: list[dict] = []
        start = 0
        chunk_index = 0
        stride = max(self._chunk_size - self._chunk_overlap, 1)

        while start < total:
            end = min(start + self._chunk_size, total)
            window = words_with_pages[start:end]
            chunks.append({
                "chunk_index": chunk_index,
                "page_number": window[0][1],
                "content": " ".join(w for w, _ in window),
            })
            chunk_index += 1
            start += stride

        return chunks
