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
