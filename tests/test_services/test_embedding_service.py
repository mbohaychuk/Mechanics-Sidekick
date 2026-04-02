from unittest.mock import MagicMock

from app.services.embedding_service import EmbeddingService
from app.services.ollama_service import OllamaService


def _make_service(embeddings: list[list[float]]) -> EmbeddingService:
    mock_ollama = MagicMock(spec=OllamaService)
    mock_ollama.embed.return_value = embeddings
    return EmbeddingService(ollama=mock_ollama, model="test-model")


def test_embed_texts_returns_all_vectors():
    svc = _make_service([[0.1, 0.2], [0.3, 0.4]])
    result = svc.embed_texts(["a", "b"])
    assert result == [[0.1, 0.2], [0.3, 0.4]]
    svc._ollama.embed.assert_called_once_with(["a", "b"], "test-model")


def test_embed_query_returns_single_vector():
    svc = _make_service([[0.5, 0.6]])
    result = svc.embed_query("what is the torque?")
    assert result == [0.5, 0.6]
    svc._ollama.embed.assert_called_once_with(["what is the torque?"], "test-model")
