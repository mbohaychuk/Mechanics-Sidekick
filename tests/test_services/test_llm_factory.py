from app.config import Settings
from app.services.embedding_service import EmbeddingService
from app.services.contextualization_service import ContextualizationService
from app.services.openai_service import OpenAIService
from app.services.ollama_service import OllamaService
from app.services.llm_factory import (
    make_embedding_service,
    make_contextualization_service,
)


def test_openai_providers_selected_by_default():
    s = Settings(_env_file=None, openai_api_key="x")

    emb = make_embedding_service(s)
    ctx = make_contextualization_service(s)

    assert isinstance(emb, EmbeddingService)
    assert isinstance(ctx, ContextualizationService)
    assert isinstance(emb._backend, OpenAIService)
    assert isinstance(ctx._backend, OpenAIService)
    assert emb._model == "text-embedding-3-small"
    assert ctx._model == "gpt-4.1-mini"


def test_ollama_selected_when_configured():
    s = Settings(_env_file=None, embed_provider="ollama", llm_provider="ollama")

    emb = make_embedding_service(s)
    ctx = make_contextualization_service(s)

    assert isinstance(emb._backend, OllamaService)
    assert isinstance(ctx._backend, OllamaService)
    assert emb._model == "nomic-embed-text"
    assert ctx._model == "llama3.2:3b"
