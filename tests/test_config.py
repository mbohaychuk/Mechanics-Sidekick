from app.config import Settings


def test_settings_has_defaults():
    s = Settings(_env_file=None)
    assert s.ollama_base_url == "http://localhost:11434"
    assert s.chat_model == "llama3.2:3b"
    assert s.context_model == "llama3.2:3b"
    assert s.embed_model == "nomic-embed-text"
    assert s.chunk_size == 500
    assert s.chunk_overlap == 100
    assert s.top_k_chunks == 5
    assert s.recent_messages == 6


def test_settings_have_openai_and_api_defaults():
    s = Settings(_env_file=None)
    assert s.llm_provider == "openai"
    assert s.embed_provider == "openai"
    assert s.openai_chat_model == "gpt-4.1-mini"
    assert s.openai_embed_model == "text-embedding-3-small"
    assert s.openai_api_key == ""
    assert s.api_host == "127.0.0.1"
    assert s.api_port == 8000
    assert s.cors_origin == "http://localhost:5173"
    assert s.spa_dist_dir == "frontend/dist"
