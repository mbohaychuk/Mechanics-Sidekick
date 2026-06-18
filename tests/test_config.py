from app.config import Settings


def test_settings_have_openai_and_api_defaults():
    s = Settings(_env_file=None)
    assert s.llm_provider == "openai"
    assert s.embed_provider == "openai"
    assert s.openai_chat_model == "gpt-4.1-mini"
    assert s.openai_embed_model == "text-embedding-3-small"
    assert s.api_port == 8000
    assert s.cors_origin == "http://localhost:5173"
    assert s.spa_dist_dir == "frontend/dist"
