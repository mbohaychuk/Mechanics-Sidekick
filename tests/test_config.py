from app.config import Settings


def test_settings_has_defaults():
    s = Settings(_env_file=None)
    assert s.ollama_base_url == "http://localhost:11434"
    assert s.chat_model == "gemma4:26b"
    assert s.context_model == "gemma4:e4b"
    assert s.embed_model == "qwen3-embedding:4b"
    assert s.chunk_size == 500
    assert s.chunk_overlap == 100
    assert s.top_k_chunks == 5
    assert s.recent_messages == 6
