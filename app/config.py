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

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
