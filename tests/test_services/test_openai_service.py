from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.openai_service import OpenAIService


def test_embed_returns_one_vector_per_text():
    client = MagicMock()
    client.embeddings.create.return_value = SimpleNamespace(
        data=[SimpleNamespace(embedding=[0.1, 0.2]), SimpleNamespace(embedding=[0.3, 0.4])]
    )
    svc = OpenAIService(api_key="x", client=client)

    result = svc.embed(["a", "b"], model="text-embedding-3-small")

    assert result == [[0.1, 0.2], [0.3, 0.4]]
    client.embeddings.create.assert_called_once_with(
        model="text-embedding-3-small", input=["a", "b"]
    )


def test_chat_returns_message_content():
    client = MagicMock()
    client.chat.completions.create.return_value = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="hello"))]
    )
    svc = OpenAIService(api_key="x", client=client)

    result = svc.chat([{"role": "user", "content": "hi"}], model="gpt-4.1-mini")

    assert result == "hello"
    client.chat.completions.create.assert_called_once_with(
        model="gpt-4.1-mini", messages=[{"role": "user", "content": "hi"}]
    )
