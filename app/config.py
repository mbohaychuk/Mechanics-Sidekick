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
    max_agent_iters: int = 6
    llm_provider: str = "openai"
    embed_provider: str = "openai"
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4.1-mini"
    openai_embed_model: str = "text-embedding-3-small"
    api_host: str = "127.0.0.1"
    api_port: int = 8000
    cors_origin: str = "http://localhost:5173"
    spa_dist_dir: str = "frontend/dist"
    max_upload_bytes: int = 100 * 1024 * 1024
    obd_mcp_enabled: bool = False
    obd_mcp_dir: str = ""
    obd_port: str = "socket://localhost:35000"
    obd_tool_denylist: str = "ping,record_session"
    mcp_call_timeout_s: float = 30.0
    mcp_start_timeout_s: float = 20.0
    web_search_enabled: bool = True
    tavily_api_key: str = ""
    web_search_max_results: int = 5
    live_sample_hz: float = 1.0
    live_min_interval_s: float = 0.25
    live_max_pids: int = 16
    live_subscriber_queue: int = 2
    live_recorder_batch: int = 20
    diag_enabled: bool = True
    diag_protocol: str = "default"
    diag_commentary_interval_s: float = 5.0
    diag_commentary_max_tokens: int = 160
    diag_commentary_window_s: float = 15.0
    diag_commentary_max_points: int = 20
    diag_max_adhoc_steps: int = 2
    diag_fuel_trim_pct: float = 10.0
    diag_coolant_max_c: float = 105.0
    diag_idle_rpm_jitter: float = 150.0
    diag_manual_min_score: float = 0.35
    diag_report_recent_limit: int = 3

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
