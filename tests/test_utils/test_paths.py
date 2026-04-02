# tests/test_utils/test_paths.py
from pathlib import Path
from app.utils.paths import get_document_path


def test_get_document_path_returns_path_object():
    result = get_document_path("./data/documents", 1, 42, "service manual.pdf")
    assert isinstance(result, Path)


def test_get_document_path_structure():
    result = get_document_path("./data/documents", 1, 42, "service manual.pdf")
    assert result == Path("./data/documents/1/42_service_manual.pdf")


def test_get_document_path_preserves_extension():
    result = get_document_path("./data/documents", 2, 7, "brake_guide.pdf")
    assert result.suffix == ".pdf"
    assert result.parent == Path("./data/documents/2")
