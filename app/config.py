from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    ollama_base_url: str = "http://localhost:11434"
    chat_model: str = "gemma4:26b"
    context_model: str = "gemma4:e4b"
    embed_model: str = "qwen3-embedding:4b"
    db_path: str = "./data/app.db"
    docs_dir: str = "./data/documents"
    chunk_size: int = 500
    chunk_overlap: int = 100
    recent_messages: int = 6
    vec_dim: int = 2560

    # Hybrid retrieval (Plan 2)
    bm25_top_k: int = 30
    vector_top_k: int = 30
    rrf_k: int = 60
    rerank_top_k: int = 10
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
