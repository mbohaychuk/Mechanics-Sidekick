from app.config import Settings
from app.services.embedding_service import EmbeddingService
from app.services.contextualization_service import ContextualizationService
from app.services.openai_service import OpenAIService
from app.services.ollama_service import OllamaService
import sys
import types

from app.services.llm_factory import (
    make_embedding_service,
    make_contextualization_service,
    make_reranker,
)
from app.services.reranker import FlashRankReranker, NoOpReranker


def test_openai_providers_selected_by_default():
    s = Settings(_env_file=None, openai_api_key="x")

    emb = make_embedding_service(s)
    ctx = make_contextualization_service(s)

    assert isinstance(emb, EmbeddingService)
    assert isinstance(ctx, ContextualizationService)
    assert isinstance(emb._backend, OpenAIService)
    assert isinstance(ctx._backend, OpenAIService)
    assert emb._model == "text-embedding-3-small"
    assert ctx._model == "gpt-5.4"


def test_ollama_selected_when_configured():
    s = Settings(_env_file=None, embed_provider="ollama", llm_provider="ollama")

    emb = make_embedding_service(s)
    ctx = make_contextualization_service(s)

    assert isinstance(emb._backend, OllamaService)
    assert isinstance(ctx._backend, OllamaService)
    assert emb._model == "nomic-embed-text"
    assert ctx._model == "llama3.2:3b"


def test_make_reranker_defaults_to_noop():
    assert isinstance(make_reranker(Settings(_env_file=None)), NoOpReranker)


def test_make_reranker_local_builds_flashrank_without_real_model(monkeypatch):
    fake = types.ModuleType("flashrank")
    fake.Ranker = lambda model_name: ("ranker", model_name)  # never load the real model in tests
    fake.RerankRequest = object
    monkeypatch.setitem(sys.modules, "flashrank", fake)

    reranker = make_reranker(Settings(_env_file=None, rerank_provider="local", rerank_model="m"))
    assert isinstance(reranker, FlashRankReranker)
