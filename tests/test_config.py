from app.config import settings


def test_settings_has_defaults():
    assert settings.ollama_base_url == "http://localhost:11434"
    assert settings.chat_model == "gpt-oss:20b"
    assert settings.embed_model == "qwen3-embedding:4b"
    assert settings.chunk_size == 1000
    assert settings.chunk_overlap == 200
    assert settings.top_k_chunks == 5
    assert settings.recent_messages == 6
