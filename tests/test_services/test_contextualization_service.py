# tests/test_services/test_contextualization_service.py
from unittest.mock import MagicMock

from app.services.contextualization_service import ContextualizationService
from app.services.ollama_service import OllamaService


def _make_svc():
    mock_ollama = MagicMock(spec=OllamaService)
    mock_ollama.chat.return_value = "This chunk covers 4.2L engine head torque specs."
    return ContextualizationService(mock_ollama, model="test-model"), mock_ollama


def test_generate_context_returns_ollama_response():
    svc, _ = _make_svc()
    result = svc.generate_context(
        chunk_content="Tighten head bolts to 23 Nm in sequence.",
        filename="10-ENGINE ASSEMBLY 4.2L.pdf",
        page_number=45,
        chunk_index=0,
        total_chunks=10,
    )
    assert result == "This chunk covers 4.2L engine head torque specs."


def test_generate_context_includes_filename_in_prompt():
    svc, mock_ollama = _make_svc()
    svc.generate_context(
        chunk_content="Some content",
        filename="15-ENGINE-CYLINDER HEAD,VALVETRAIN 6.0L.pdf",
        page_number=1,
        chunk_index=2,
        total_chunks=20,
    )
    prompt_text = mock_ollama.chat.call_args[0][0][0]["content"]
    assert "15-ENGINE-CYLINDER HEAD,VALVETRAIN 6.0L.pdf" in prompt_text


def test_generate_context_includes_page_number_in_prompt():
    svc, mock_ollama = _make_svc()
    svc.generate_context(
        chunk_content="Some content",
        filename="manual.pdf",
        page_number=99,
        chunk_index=0,
        total_chunks=5,
    )
    prompt_text = mock_ollama.chat.call_args[0][0][0]["content"]
    assert "99" in prompt_text


def test_generate_context_handles_none_page_number():
    svc, _ = _make_svc()
    result = svc.generate_context(
        chunk_content="Some content",
        filename="manual.pdf",
        page_number=None,
        chunk_index=0,
        total_chunks=5,
    )
    assert isinstance(result, str)
