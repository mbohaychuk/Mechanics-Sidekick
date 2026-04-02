from app.services.chunking_service import ChunkingService


def test_chunks_have_correct_structure():
    svc = ChunkingService(chunk_size=5, chunk_overlap=1)
    pages = [{"page_number": 1, "text": "a b c d e f g h i j"}]
    chunks = svc.chunk_pages(pages)
    assert len(chunks) > 0
    for chunk in chunks:
        assert "chunk_index" in chunk
        assert "page_number" in chunk
        assert "content" in chunk
        assert isinstance(chunk["chunk_index"], int)


def test_overlap_words_appear_in_consecutive_chunks():
    svc = ChunkingService(chunk_size=5, chunk_overlap=2)
    pages = [{"page_number": 1, "text": "a b c d e f g h i j"}]
    chunks = svc.chunk_pages(pages)
    # chunk 0: a b c d e
    # chunk 1: d e f g h  (2-word overlap)
    assert len(chunks) >= 2
    words_c0 = chunks[0]["content"].split()
    words_c1 = chunks[1]["content"].split()
    assert words_c0[-2:] == words_c1[:2]


def test_empty_pages_returns_no_chunks():
    svc = ChunkingService(chunk_size=100, chunk_overlap=10)
    assert svc.chunk_pages([]) == []


def test_page_number_tracks_source_page():
    svc = ChunkingService(chunk_size=5, chunk_overlap=0)
    pages = [
        {"page_number": 3, "text": "a b c d e"},
        {"page_number": 7, "text": "f g h i j"},
    ]
    chunks = svc.chunk_pages(pages)
    assert chunks[0]["page_number"] == 3
    assert chunks[1]["page_number"] == 7


def test_chunk_indices_are_sequential():
    svc = ChunkingService(chunk_size=3, chunk_overlap=0)
    pages = [{"page_number": 1, "text": "a b c d e f g h i"}]
    chunks = svc.chunk_pages(pages)
    for i, chunk in enumerate(chunks):
        assert chunk["chunk_index"] == i
