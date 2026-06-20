from app import cli
from app.services.openai_service import OpenAIService


def test_cli_chat_service_embeds_queries_with_configured_provider(db_session, monkeypatch):
    # The CLI must embed queries with the SAME provider as ingestion (the configured
    # embed_provider), not a hardcoded Ollama model — otherwise query and corpus vectors
    # live in different spaces/dimensions and retrieval crashes or returns garbage.
    monkeypatch.setattr(cli.settings, "embed_provider", "openai")
    monkeypatch.setattr(cli.settings, "openai_api_key", "sk-test")

    svc = cli._make_chat_service(db_session)
    backend = svc._retrieval._embedding_service._backend

    assert isinstance(backend, OpenAIService)
