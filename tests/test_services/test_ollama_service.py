from unittest.mock import MagicMock, patch

from app.services.ollama_service import OllamaService


def _make_service() -> tuple[OllamaService, MagicMock]:
    with patch("app.services.ollama_service.ollama.Client") as MockClient:
        mock_client = MagicMock()
        MockClient.return_value = mock_client
        svc = OllamaService(base_url="http://localhost:11434")
    return svc, mock_client


def test_embed_returns_embeddings():
    svc, mock_client = _make_service()
    expected = [[0.1, 0.2], [0.3, 0.4]]
    mock_client.embed.return_value = MagicMock(embeddings=expected)

    result = svc.embed(["hello", "world"], model="test-model")

    mock_client.embed.assert_called_once_with(model="test-model", input=["hello", "world"])
    assert result == expected


def test_chat_returns_content():
    svc, mock_client = _make_service()
    mock_client.chat.return_value = MagicMock(message=MagicMock(content="42 ft-lbs"))

    result = svc.chat([{"role": "user", "content": "torque spec?"}], model="test-model")

    mock_client.chat.assert_called_once_with(
        model="test-model", messages=[{"role": "user", "content": "torque spec?"}]
    )
    assert result == "42 ft-lbs"
