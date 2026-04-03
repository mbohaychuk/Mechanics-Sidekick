# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Install all dependencies (including dev)
uv sync --group dev

# Run all tests
uv run pytest tests/ -v

# Run a single test file
uv run pytest tests/test_services/test_chat_service.py -v

# Run the CLI
uv run mechanic-sidekick --help
uv run mechanic-sidekick vehicle add
uv run mechanic-sidekick document add <vehicle_id> <path/to/manual.pdf>
uv run mechanic-sidekick job add <vehicle_id>
uv run mechanic-sidekick chat start <job_id>
```

Ollama must be running locally (`ollama serve`) for `document add` and `chat` commands.
Chat model: `gpt-oss:20b` (fallback: `qwen3.5:9b`). Embedding model: `qwen3-embedding:4b`.

## Architecture

**Core workflow:** Vehicle → Documents (PDFs) → Jobs → Chat

At ingestion (`document add`): PDF text is extracted page-by-page via PyMuPDF, split into overlapping word-based chunks, each chunk is embedded via Ollama, and stored as JSON in the `document_chunks` SQLite table.

At query time (`chat ask` / `chat start`): the question is embedded, cosine-ranked against all chunks for that vehicle (not all vehicles), and the top K chunks are injected into an Ollama chat prompt alongside recent job history.

**Layer responsibilities:**
- `app/cli.py` — Typer commands; assembles services via factory functions (`_make_*_service`); each command opens/closes its own DB session
- `app/services/` — orchestration; each service depends only on repositories and other services injected at construction
- `app/repositories/` — all SQLAlchemy queries; repositories accept a `Session` in `__init__`
- `app/rag/` — `similarity.py` (cosine ranking), `prompt_builder.py` (system prompt + messages list)
- `app/utils/` — `paths.py` (deterministic PDF storage path), `console.py` (Rich output helpers)
- `app/models/` — SQLAlchemy 2.0 `mapped_column` style; all models registered in `__init__.py`

**DB session pattern in CLI:** `get_session()` is a context manager that creates engine lazily (calls `Base.metadata.create_all` once), yields a session, commits on success, rollbacks on exception.

**Testing:** All tests use an in-memory SQLite engine via `db_session` fixture in `tests/conftest.py`. Ollama-dependent services (`OllamaService`, `EmbeddingService`) are always mocked with `MagicMock(spec=...)`.

## Key Config (via .env or environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `CHAT_MODEL` | `gpt-oss:20b` | Ollama chat model |
| `EMBED_MODEL` | `qwen3-embedding:4b` | Ollama embedding model |
| `DB_PATH` | `./data/app.db` | SQLite database file |
| `DOCS_DIR` | `./data/documents` | Local PDF storage root |
| `CHUNK_SIZE` | `1000` | Words per chunk |
| `CHUNK_OVERLAP` | `200` | Overlap words between chunks |
| `TOP_K_CHUNKS` | `5` | Chunks retrieved per question |
| `RECENT_MESSAGES` | `6` | Chat history messages sent to LLM |
