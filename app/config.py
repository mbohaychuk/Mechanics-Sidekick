from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    chat_model: str = "llama3.2:3b"
    context_model: str = "llama3.2:3b"
    embed_model: str = "nomic-embed-text"
    db_path: str = "./data/app.db"
    docs_dir: str = "./data/documents"
    chunk_size: int = 500
    chunk_overlap: int = 100
    top_k_chunks: int = 5
    recent_messages: int = 6
    llm_provider: str = "openai"
    embed_provider: str = "openai"
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4.1-mini"
    openai_embed_model: str = "text-embedding-3-small"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origin: str = "http://localhost:5173"
    spa_dist_dir: str = "frontend/dist"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
