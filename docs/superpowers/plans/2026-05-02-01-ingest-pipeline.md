# Ingest Pipeline + Schema Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the in-row JSON embedding with a SQLite-native hybrid index (FTS5 + sqlite-vec), add table-aware chunking with engine-variant metadata, and rebuild the corpus with the new schema. After this plan ships, every chunk lives in three places (`document_chunks`, `document_chunks_fts`, `document_chunks_vec`) and carries `chunk_kind`, `engine_variant`, `table_type`, `table_id` so the retrieval rewrite (Plan 2) has everything it needs.

**Architecture:** Hard cutover. We drop existing chunk rows (no production data), `ALTER TABLE` for new columns, drop `embedding_json`, create two virtual tables. Ingest gets a new `TableChunker` that runs *before* `StructuredChunkingService` and excludes table bbox regions. A `MetadataExtractor` populates engine-variant tags via filename regex with an LLM fallback. `ChunkRepository.bulk_create` writes to all three tables in one call. A new `mechanic-sidekick db reset` command nukes `data/app.db` and `data/documents/*` for clean re-ingest.

**Tech Stack:** Python 3.11, SQLAlchemy 2.0 (mapped_column style), `sqlite-vec` 0.1+ (vec0 virtual tables), SQLite FTS5 (built into sqlite3), PyMuPDF (Page.find_tables), Ollama (gemma4:e4b for variant fallback), Typer, pytest.

---

## Source Spec

`docs/superpowers/specs/2026-05-01-agentic-rag-loop-design.md` — Sections 2 (ingest), 6 (schema, config, testing).

## File Structure

**Created:**
- `app/services/table_chunker.py` — emits `table_row` and `table_whole` chunks via PyMuPDF.find_tables
- `app/services/metadata_extractor.py` — engine-variant + table_type classifier (filename regex + LLM fallback)
- `app/db/__init__.py` — package marker (the existing `app/db.py` becomes `app/db/session.py`)
- `app/db/session.py` — moved from `app/db.py`; loads sqlite-vec extension on engine create
- `app/db/migrations.py` — one-shot `apply_hybrid_retrieval_migration(engine)` — drops chunks, alters table, creates virtual tables
- `tests/test_services/test_table_chunker.py`
- `tests/test_services/test_metadata_extractor.py`
- `tests/test_db/__init__.py`
- `tests/test_db/test_migrations.py`

**Modified:**
- `app/db.py` → deleted, replaced by `app/db/` package
- `app/models/document_chunk.py` — add `chunk_kind`, `engine_variant`, `table_type`, `table_id` columns; drop `embedding_json`
- `app/repositories/chunk_repository.py` — `bulk_create` writes to FTS5 + vec0 too; `list_by_vehicle` no longer references `embedding_json`
- `app/services/document_service.py` — invoke `TableChunker` first, then `StructuredChunkingService` on non-table regions, then `MetadataExtractor`, then `ContextualizationService`, then `EmbeddingService`, then bulk-insert into all three tables
- `app/services/structured_chunking_service.py` — accept an `exclude_bboxes_per_page` argument so prose chunking skips table regions
- `app/services/pdf_service.py` — add `extract_tables(pdf_path)` method
- `app/cli.py` — `_make_document_service` wires in `TableChunker` + `MetadataExtractor`; add `db reset` command; ensure `_get_engine` runs the migration; recurse into subdirectories on `document add`
- `app/config.py` — drop `top_k_chunks` (subsumed by Plan 2's `rerank_top_k`); add `vec_dim` (embedding dimension, 2560 for `qwen3-embedding:4b`)
- `pyproject.toml` — add `sqlite-vec>=0.1`
- `tests/conftest.py` — apply migration after `Base.metadata.create_all`; load sqlite-vec extension on the in-memory engine
- All existing chunk-related tests (`test_chunk_repository.py`, `test_document_service.py`, `test_retrieval_service.py`) — update to the new schema

**Deleted:** none in this plan (Plan 2 deletes `retrieval_service.py`; Plan 3 deletes `chat_service.py`).

## Branch Strategy

Single feature branch `feature/agentic-rag` for all four plans. Each plan's tasks become commits on this branch. Plans 1-3 are sequential (each depends on the prior). Plan 4 (evals) is independent and could be parallel, but in practice we sequence it last so we can run it against the full pipeline.

---

## Task 1: Add sqlite-vec dependency and create db package

**Files:**
- Modify: `pyproject.toml`
- Create: `app/db/__init__.py`
- Create: `app/db/session.py` (moved from `app/db.py`)
- Delete: `app/db.py`

- [ ] **Step 1: Add the dependency**

Edit `pyproject.toml` — add `"sqlite-vec>=0.1"` to `dependencies`:

```toml
dependencies = [
    "ollama>=0.4",
    "sqlalchemy>=2.0",
    "pydantic-settings>=2.0",
    "pymupdf>=1.24",
    "typer>=0.12",
    "rich>=13.0",
    "numpy>=1.26",
    "python-dotenv>=1.0",
    "sqlite-vec>=0.1",
]
```

- [ ] **Step 2: Sync**

Run: `uv sync --group dev`
Expected: installs `sqlite-vec` (~5MB binary wheel).

- [ ] **Step 3: Create the package marker**

Create `app/db/__init__.py`:

```python
# app/db/__init__.py
from app.db.session import Base, get_engine, get_session_factory

__all__ = ["Base", "get_engine", "get_session_factory"]
```

- [ ] **Step 4: Move session module + load sqlite-vec extension**

Create `app/db/session.py`:

```python
# app/db/session.py
import sqlite_vec
from sqlalchemy import create_engine, event, Engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase


class Base(DeclarativeBase):
    pass


def get_engine(db_url: str) -> Engine:
    engine = create_engine(db_url, connect_args={"check_same_thread": False})

    @event.listens_for(engine, "connect")
    def _load_extensions(dbapi_conn, _record):
        dbapi_conn.enable_load_extension(True)
        sqlite_vec.load(dbapi_conn)
        dbapi_conn.enable_load_extension(False)

    return engine


def get_session_factory(engine: Engine):
    return sessionmaker(bind=engine, expire_on_commit=False)
```

Delete `app/db.py`:

```bash
rm app/db.py
```

- [ ] **Step 5: Verify imports still resolve**

Run: `uv run python -c "from app.db import Base, get_engine, get_session_factory; print('ok')"`
Expected: `ok`

- [ ] **Step 6: Verify the existing test suite still passes**

Run: `uv run pytest tests/ -v`
Expected: all green (we haven't changed any behaviour yet — only the module location).

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock app/db/__init__.py app/db/session.py
git rm app/db.py
git commit -m "refactor: move db module into package; load sqlite-vec on connect"
```

---

## Task 2: Update DocumentChunk model schema

**Files:**
- Modify: `app/models/document_chunk.py`
- Test: `tests/test_db/test_migrations.py` (new file, used by next task — referenced here for orientation only)

- [ ] **Step 1: Update the model**

Replace `app/models/document_chunk.py` with:

```python
# app/models/document_chunk.py
from sqlalchemy import ForeignKey, Text, String
from sqlalchemy.orm import Mapped, mapped_column
from app.db import Base


class DocumentChunk(Base):
    __tablename__ = "document_chunks"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    document_id: Mapped[int] = mapped_column(ForeignKey("documents.id"))
    chunk_index: Mapped[int] = mapped_column()
    page_number: Mapped[int | None] = mapped_column(nullable=True)
    content: Mapped[str] = mapped_column(Text)
    section_title: Mapped[str | None] = mapped_column(Text, nullable=True)
    context_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    chunk_kind: Mapped[str] = mapped_column(String(16), default="prose")
    engine_variant: Mapped[str | None] = mapped_column(String(16), nullable=True)
    table_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    table_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
```

Note: `embedding_json` is gone. Embeddings now live in `document_chunks_vec`.

- [ ] **Step 2: Run the test suite — expect failures**

Run: `uv run pytest tests/ -v`
Expected: FAIL — many tests reference `embedding_json` or `top_k_chunks`. Note the failing test IDs; we'll fix them in Task 3 and again as we go through dependent tasks. Tests that currently pass should still pass.

- [ ] **Step 3: Update the chunk repository test fixtures**

Edit `tests/test_repositories/test_chunk_repository.py` — remove the `embedding_json=...` argument from every `DocumentChunk(...)` construction. Replace `import json` removal if no longer needed. The new `bulk_create` in Task 4 will require an embedding argument; for now this test only exercises `list_by_vehicle`, so leave it embedding-free.

The full updated file:

```python
# tests/test_repositories/test_chunk_repository.py
import pytest
from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.chunk_repository import ChunkRepository
from app.models.document_chunk import DocumentChunk


@pytest.fixture
def vehicle_and_ready_doc(db_session):
    vehicle = VehicleRepository(db_session).create(year=2018, make="Ford", model="F-150", engine="5.0L")
    db_session.flush()
    doc = DocumentRepository(db_session).create(vehicle.id, "manual.pdf", "/tmp/manual.pdf")
    doc.processing_status = "ready"
    db_session.flush()
    return vehicle, doc


def test_list_by_vehicle_returns_chunks_in_order(db_session, vehicle_and_ready_doc):
    vehicle, doc = vehicle_and_ready_doc
    chunk_repo = ChunkRepository(db_session)
    db_session.add_all([
        DocumentChunk(document_id=doc.id, chunk_index=0, page_number=1, content="Torque spec is 129 Nm"),
        DocumentChunk(document_id=doc.id, chunk_index=1, page_number=2, content="Rotor thickness 20mm"),
    ])
    db_session.flush()

    results = chunk_repo.list_by_vehicle(vehicle.id)
    assert len(results) == 2
    assert results[0].content == "Torque spec is 129 Nm"


def test_list_by_vehicle_excludes_pending_docs(db_session):
    vehicle = VehicleRepository(db_session).create(year=2019, make="GM", model="Sierra", engine="5.3L")
    db_session.flush()

    doc_repo = DocumentRepository(db_session)
    ready_doc = doc_repo.create(vehicle.id, "ready.pdf", "/tmp/ready.pdf")
    ready_doc.processing_status = "ready"
    pending_doc = doc_repo.create(vehicle.id, "pending.pdf", "/tmp/pending.pdf")
    db_session.flush()

    db_session.add_all([
        DocumentChunk(document_id=ready_doc.id, chunk_index=0, page_number=1, content="Ready content"),
        DocumentChunk(document_id=pending_doc.id, chunk_index=0, page_number=1, content="Pending content"),
    ])
    db_session.flush()

    results = ChunkRepository(db_session).list_by_vehicle(vehicle.id)
    assert len(results) == 1
    assert results[0].content == "Ready content"
```

- [ ] **Step 4: Run that test file — expect pass**

Run: `uv run pytest tests/test_repositories/test_chunk_repository.py -v`
Expected: both tests PASS. (`list_by_vehicle` doesn't currently filter on `embedding_json`, so it works.)

- [ ] **Step 5: Don't commit yet**

We're mid-schema. Wait for Task 3 (the migration) before committing — otherwise the model and the SQL are out of sync on disk.

---

## Task 3: Migration script + virtual tables

**Files:**
- Create: `app/db/migrations.py`
- Create: `tests/test_db/__init__.py`
- Create: `tests/test_db/test_migrations.py`
- Modify: `tests/conftest.py`
- Modify: `app/cli.py` (only the `_get_engine` helper)

- [ ] **Step 1: Write the failing migration test**

Create `tests/test_db/__init__.py` (empty). Create `tests/test_db/test_migrations.py`:

```python
# tests/test_db/test_migrations.py
"""The migration creates FTS5 + vec0 virtual tables and the new metadata columns."""
from sqlalchemy import inspect, text
from app.db import Base, get_engine
from app.db.migrations import apply_hybrid_retrieval_migration
import app.models  # noqa: F401


def test_migration_adds_columns_and_creates_virtual_tables(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)

    apply_hybrid_retrieval_migration(engine, vec_dim=4)

    inspector = inspect(engine)
    cols = {c["name"] for c in inspector.get_columns("document_chunks")}
    assert "chunk_kind" in cols
    assert "engine_variant" in cols
    assert "table_type" in cols
    assert "table_id" in cols
    assert "embedding_json" not in cols

    with engine.connect() as conn:
        tables = {r[0] for r in conn.execute(text(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )).fetchall()}
        assert "document_chunks_fts" in tables
        assert "document_chunks_vec" in tables


def test_migration_is_idempotent(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)

    apply_hybrid_retrieval_migration(engine, vec_dim=4)
    apply_hybrid_retrieval_migration(engine, vec_dim=4)  # second call must not raise


def test_migration_drops_existing_chunks(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)

    with engine.connect() as conn:
        conn.execute(text("INSERT INTO vehicles (year, make, model, engine) VALUES (2018, 'Ford', 'F-150', '5.0L')"))
        conn.execute(text(
            "INSERT INTO documents (vehicle_id, file_name, stored_path, document_type, processing_status) "
            "VALUES (1, 'a.pdf', '/tmp/a.pdf', 'service_manual', 'ready')"
        ))
        conn.execute(text(
            "INSERT INTO document_chunks (document_id, chunk_index, content) VALUES (1, 0, 'old')"
        ))
        conn.commit()

    apply_hybrid_retrieval_migration(engine, vec_dim=4)

    with engine.connect() as conn:
        row_count = conn.execute(text("SELECT COUNT(*) FROM document_chunks")).scalar()
        assert row_count == 0
```

- [ ] **Step 2: Run — expect import failure**

Run: `uv run pytest tests/test_db/test_migrations.py -v`
Expected: FAIL — `app.db.migrations` does not exist.

- [ ] **Step 3: Implement the migration**

Create `app/db/migrations.py`:

```python
# app/db/migrations.py
"""One-shot migration to the hybrid retrieval schema.

Drops existing chunk rows (no production data), adds metadata columns to
document_chunks, removes the legacy embedding_json column, and creates the
FTS5 + sqlite-vec virtual tables that Plan 2's retrieval pipeline reads.

Idempotent: running twice on the same engine is a no-op.
"""
from sqlalchemy import Engine, inspect, text


_NEW_COLUMNS = (
    ("chunk_kind", "TEXT NOT NULL DEFAULT 'prose'"),
    ("engine_variant", "TEXT NULL"),
    ("table_type", "TEXT NULL"),
    ("table_id", "TEXT NULL"),
)


def apply_hybrid_retrieval_migration(engine: Engine, vec_dim: int) -> None:
    inspector = inspect(engine)
    existing_cols = {c["name"] for c in inspector.get_columns("document_chunks")}
    existing_tables = set(inspector.get_table_names())

    with engine.begin() as conn:
        # 1. Drop chunk rows from any prior schema (no production data).
        conn.execute(text("DELETE FROM document_chunks"))

        # 2. Drop legacy embedding_json column if present.
        if "embedding_json" in existing_cols:
            conn.execute(text("ALTER TABLE document_chunks DROP COLUMN embedding_json"))

        # 3. Add new metadata columns idempotently.
        for col_name, col_decl in _NEW_COLUMNS:
            if col_name not in existing_cols:
                conn.execute(text(f"ALTER TABLE document_chunks ADD COLUMN {col_name} {col_decl}"))

        # 4. Indexes for the engine_variant filter and table grouping.
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_chunks_engine_variant ON document_chunks(engine_variant)"
        ))
        conn.execute(text(
            "CREATE INDEX IF NOT EXISTS idx_chunks_table_id ON document_chunks(table_id)"
        ))

        # 5. FTS5 virtual table over the contextualized text (the same enriched
        # text that gets embedded). content='' = external content; we manage
        # rows manually from chunk_repository.
        if "document_chunks_fts" not in existing_tables:
            conn.execute(text(
                "CREATE VIRTUAL TABLE document_chunks_fts USING fts5("
                "  chunk_id UNINDEXED,"
                "  text,"
                "  content=''"
                ")"
            ))

        # 6. sqlite-vec virtual table for cosine similarity.
        if "document_chunks_vec" not in existing_tables:
            conn.execute(text(
                f"CREATE VIRTUAL TABLE document_chunks_vec USING vec0("
                f"  chunk_id INTEGER PRIMARY KEY,"
                f"  embedding FLOAT[{vec_dim}]"
                f")"
            ))
```

- [ ] **Step 4: Run the migration tests — expect pass**

Run: `uv run pytest tests/test_db/test_migrations.py -v`
Expected: all three tests PASS.

- [ ] **Step 5: Wire migration into conftest**

Replace `tests/conftest.py`:

```python
# tests/conftest.py
import pytest
from sqlalchemy import event
import sqlite_vec
from sqlalchemy.orm import sessionmaker

from app.db import Base, get_engine
from app.db.migrations import apply_hybrid_retrieval_migration
import app.models  # noqa: F401


@pytest.fixture(scope="function")
def db_engine():
    # In-memory engine — sqlite-vec already loaded by get_engine().
    engine = get_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    apply_hybrid_retrieval_migration(engine, vec_dim=4)
    yield engine
    Base.metadata.drop_all(engine)
    engine.dispose()


@pytest.fixture(scope="function")
def db_session(db_engine):
    Session = sessionmaker(bind=db_engine, expire_on_commit=False)
    session = Session()
    yield session
    session.rollback()
    session.close()
```

- [ ] **Step 6: Wire migration into the CLI engine bootstrap**

Edit `app/cli.py` `_get_engine()` — after `Base.metadata.create_all(_engine)`, call the migration. Replace the function:

```python
def _get_engine():
    global _engine, _Session
    if _engine is None:
        import app.models  # noqa: F401 — register all models with Base
        from app.db.migrations import apply_hybrid_retrieval_migration

        db_path = Path(settings.db_path)
        db_path.parent.mkdir(parents=True, exist_ok=True)
        _engine = get_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(_engine)
        apply_hybrid_retrieval_migration(_engine, vec_dim=settings.vec_dim)
        _Session = get_session_factory(_engine)
    return _engine
```

We'll add `vec_dim` to `Settings` next.

- [ ] **Step 7: Add vec_dim to Settings**

Edit `app/config.py`:

```python
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
    top_k_chunks: int = 5
    recent_messages: int = 6
    vec_dim: int = 2560  # qwen3-embedding:4b dimension

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
```

`top_k_chunks` is *not* removed yet — Plan 2 deletes it when `RetrievalService` is gone.

- [ ] **Step 8: Run the full test suite**

Run: `uv run pytest tests/ -v`
Expected: most pass; `test_retrieval_service.py` will still fail because it constructs `DocumentChunk(embedding_json=...)`. We'll fix retrieval-related tests when Plan 2 replaces them. For now, mark them xfail-ish: edit `tests/test_services/test_retrieval_service.py` to skip the file:

```python
# tests/test_services/test_retrieval_service.py
import pytest

pytestmark = pytest.mark.skip(reason="RetrievalService is replaced by HybridRetrievalService in Plan 2")
```

(Delete the rest of the file body.)

Same for `tests/test_services/test_chat_service.py` — the chunk fixture constructs `embedding_json`. Skip the file:

```python
# tests/test_services/test_chat_service.py
import pytest

pytestmark = pytest.mark.skip(reason="ChatService is replaced by AgenticChatService in Plan 3")
```

Run again: `uv run pytest tests/ -v`
Expected: all green; the two retrieval/chat test files are skipped.

- [ ] **Step 9: Verify CLI bootstrap still works**

Run: `uv run mechanic-sidekick --help`
Expected: shows the help (no errors loading the engine — migration is idempotent on an existing dev DB).

If you have a `data/app.db` from a prior run, also try:

```bash
uv run mechanic-sidekick vehicle list
```

Expected: lists existing vehicles or "No vehicles found." No tracebacks.

- [ ] **Step 10: Commit**

```bash
git add app/models/document_chunk.py app/db/migrations.py app/config.py app/cli.py
git add tests/test_db/__init__.py tests/test_db/test_migrations.py tests/conftest.py
git add tests/test_repositories/test_chunk_repository.py
git add tests/test_services/test_retrieval_service.py tests/test_services/test_chat_service.py
git commit -m "feat: add hybrid retrieval schema (FTS5 + vec0) and migration"
```

---

## Task 4: ChunkRepository writes to all three tables

**Files:**
- Modify: `app/repositories/chunk_repository.py`
- Modify: `tests/test_repositories/test_chunk_repository.py`

The repository now owns the invariant: every chunk row in `document_chunks` has a matching row in `document_chunks_fts` (text) and `document_chunks_vec` (embedding). `bulk_create` takes embeddings + indexable text alongside the chunk objects so callers can't forget to update one of the three.

- [ ] **Step 1: Write the failing tests**

Replace `tests/test_repositories/test_chunk_repository.py`:

```python
# tests/test_repositories/test_chunk_repository.py
import pytest
from sqlalchemy import text
from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.chunk_repository import ChunkRepository, ChunkInsert
from app.models.document_chunk import DocumentChunk


@pytest.fixture
def vehicle_and_ready_doc(db_session):
    vehicle = VehicleRepository(db_session).create(year=2018, make="Ford", model="F-150", engine="5.0L")
    db_session.flush()
    doc = DocumentRepository(db_session).create(vehicle.id, "manual.pdf", "/tmp/manual.pdf")
    doc.processing_status = "ready"
    db_session.flush()
    return vehicle, doc


def test_bulk_create_writes_to_chunks_fts_and_vec(db_session, vehicle_and_ready_doc):
    _, doc = vehicle_and_ready_doc
    repo = ChunkRepository(db_session)
    repo.bulk_create([
        ChunkInsert(
            chunk=DocumentChunk(document_id=doc.id, chunk_index=0, page_number=1, content="Torque spec is 129 Nm"),
            indexable_text="Torque spec is 129 Nm for the brake caliper",
            embedding=[0.1, 0.2, 0.3, 0.4],
        ),
        ChunkInsert(
            chunk=DocumentChunk(document_id=doc.id, chunk_index=1, page_number=2, content="Rotor thickness 20mm"),
            indexable_text="Minimum rotor thickness 20mm front discs",
            embedding=[0.5, 0.6, 0.7, 0.8],
        ),
    ])
    db_session.flush()

    fts_count = db_session.execute(text("SELECT COUNT(*) FROM document_chunks_fts")).scalar()
    vec_count = db_session.execute(text("SELECT COUNT(*) FROM document_chunks_vec")).scalar()
    assert fts_count == 2
    assert vec_count == 2

    # FTS5 chunk_id column matches document_chunks.id
    fts_ids = {row[0] for row in db_session.execute(text("SELECT chunk_id FROM document_chunks_fts")).fetchall()}
    main_ids = {row[0] for row in db_session.execute(text("SELECT id FROM document_chunks")).fetchall()}
    assert fts_ids == main_ids


def test_list_by_vehicle_returns_chunks_in_order(db_session, vehicle_and_ready_doc):
    vehicle, doc = vehicle_and_ready_doc
    repo = ChunkRepository(db_session)
    repo.bulk_create([
        ChunkInsert(
            chunk=DocumentChunk(document_id=doc.id, chunk_index=0, page_number=1, content="first"),
            indexable_text="first",
            embedding=[1.0, 0.0, 0.0, 0.0],
        ),
        ChunkInsert(
            chunk=DocumentChunk(document_id=doc.id, chunk_index=1, page_number=2, content="second"),
            indexable_text="second",
            embedding=[0.0, 1.0, 0.0, 0.0],
        ),
    ])
    db_session.flush()

    rows = repo.list_by_vehicle(vehicle.id)
    assert len(rows) == 2
    assert rows[0].content == "first"
    assert rows[1].content == "second"


def test_list_by_vehicle_excludes_pending_docs(db_session):
    vehicle = VehicleRepository(db_session).create(year=2019, make="GM", model="Sierra", engine="5.3L")
    db_session.flush()

    doc_repo = DocumentRepository(db_session)
    ready_doc = doc_repo.create(vehicle.id, "ready.pdf", "/tmp/ready.pdf")
    ready_doc.processing_status = "ready"
    pending_doc = doc_repo.create(vehicle.id, "pending.pdf", "/tmp/pending.pdf")
    db_session.flush()

    repo = ChunkRepository(db_session)
    repo.bulk_create([
        ChunkInsert(
            chunk=DocumentChunk(document_id=ready_doc.id, chunk_index=0, page_number=1, content="Ready content"),
            indexable_text="Ready content",
            embedding=[0.1, 0.0, 0.0, 0.0],
        ),
        ChunkInsert(
            chunk=DocumentChunk(document_id=pending_doc.id, chunk_index=0, page_number=1, content="Pending content"),
            indexable_text="Pending content",
            embedding=[0.0, 0.1, 0.0, 0.0],
        ),
    ])
    db_session.flush()

    rows = repo.list_by_vehicle(vehicle.id)
    assert len(rows) == 1
    assert rows[0].content == "Ready content"
```

- [ ] **Step 2: Run — expect import failure**

Run: `uv run pytest tests/test_repositories/test_chunk_repository.py -v`
Expected: FAIL — `ChunkInsert` not exported.

- [ ] **Step 3: Implement the new ChunkRepository**

Replace `app/repositories/chunk_repository.py`:

```python
# app/repositories/chunk_repository.py
"""Owns the invariant that every chunk lives in three tables.

A chunk row in document_chunks is paired with:
  - a document_chunks_fts row (BM25 over the contextualized text)
  - a document_chunks_vec row (cosine over the embedding)

bulk_create takes ChunkInsert records carrying all three pieces so callers
cannot forget one. Plan 2's HybridRetrievalService reads these tables.
"""
from dataclasses import dataclass
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.document import Document
from app.models.document_chunk import DocumentChunk


@dataclass
class ChunkInsert:
    """Single chunk to bulk-insert: row data + the text BM25 indexes + the embedding vec."""
    chunk: DocumentChunk
    indexable_text: str
    embedding: list[float]


class ChunkRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def bulk_create(self, inserts: list[ChunkInsert]) -> None:
        if not inserts:
            return
        # 1. Insert main rows; flush to populate auto-increment ids.
        self.session.add_all([ins.chunk for ins in inserts])
        self.session.flush()

        # 2. Mirror to the FTS5 and vec0 virtual tables.
        for ins in inserts:
            self.session.execute(
                text("INSERT INTO document_chunks_fts (chunk_id, text) VALUES (:cid, :txt)"),
                {"cid": ins.chunk.id, "txt": ins.indexable_text},
            )
            self.session.execute(
                text("INSERT INTO document_chunks_vec (chunk_id, embedding) VALUES (:cid, :emb)"),
                {"cid": ins.chunk.id, "emb": _serialize_vec(ins.embedding)},
            )

    def list_by_vehicle(self, vehicle_id: int) -> list[DocumentChunk]:
        """Return all chunks from ready documents belonging to this vehicle."""
        return (
            self.session.query(DocumentChunk)
            .join(Document, DocumentChunk.document_id == Document.id)
            .filter(Document.vehicle_id == vehicle_id)
            .filter(Document.processing_status == "ready")
            .order_by(DocumentChunk.document_id, DocumentChunk.chunk_index)
            .all()
        )


def _serialize_vec(embedding: list[float]) -> bytes:
    """sqlite-vec accepts a list of floats encoded as little-endian float32 bytes."""
    import struct
    return struct.pack(f"{len(embedding)}f", *embedding)
```

- [ ] **Step 4: Run the test file — expect pass**

Run: `uv run pytest tests/test_repositories/test_chunk_repository.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: green except the two skipped files.

- [ ] **Step 6: Commit**

```bash
git add app/repositories/chunk_repository.py tests/test_repositories/test_chunk_repository.py
git commit -m "feat: ChunkRepository writes chunks, FTS5, and vec0 atomically"
```

---

## Task 5: PDFService.extract_tables

**Files:**
- Modify: `app/services/pdf_service.py`
- Modify: `tests/test_services/test_pdf_service.py`

PyMuPDF's `Page.find_tables()` returns `TableFinder` objects exposing `.tables`, each with `.bbox`, `.extract()` (rows of cells), `.header` (column-header row).

- [ ] **Step 1: Write the failing test**

Append to `tests/test_services/test_pdf_service.py` (existing tests stay):

```python
def test_extract_tables_returns_per_page_table_data(tmp_path):
    """Smoke test: a PDF with a clear grid table → extract_tables yields rows + bbox."""
    import fitz
    pdf_path = tmp_path / "table.pdf"
    doc = fitz.open()
    page = doc.new_page()
    # Draw a 2x2 grid with text in cells.
    page.draw_rect(fitz.Rect(50, 50, 250, 150))
    page.draw_line(fitz.Point(50, 100), fitz.Point(250, 100))
    page.draw_line(fitz.Point(150, 50), fitz.Point(150, 150))
    page.insert_text(fitz.Point(60, 70), "Spec")
    page.insert_text(fitz.Point(160, 70), "Value")
    page.insert_text(fitz.Point(60, 120), "Torque")
    page.insert_text(fitz.Point(160, 120), "129 Nm")
    doc.save(str(pdf_path))
    doc.close()

    from app.services.pdf_service import PDFService
    pages = PDFService().extract_tables(str(pdf_path))

    assert len(pages) == 1
    assert pages[0]["page_number"] == 1
    assert len(pages[0]["tables"]) >= 1
    table = pages[0]["tables"][0]
    assert "rows" in table         # list[list[str]]
    assert "bbox" in table         # tuple[float, float, float, float]
    assert "header" in table       # list[str] | None
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_services/test_pdf_service.py -v -k extract_tables`
Expected: FAIL — `PDFService` has no `extract_tables`.

- [ ] **Step 3: Implement extract_tables**

Add to `app/services/pdf_service.py`:

```python
def extract_tables(self, pdf_path: str) -> list[dict]:
    """Detect tables page-by-page via PyMuPDF.

    Returns list of {"page_number": int, "tables": list[dict]}.
    Each table dict: {"bbox": (x0, y0, x1, y1), "header": list[str] | None, "rows": list[list[str]]}.
    Pages with no detected tables are omitted.
    """
    pages = []
    with fitz.open(pdf_path) as doc:
        for page_num, page in enumerate(doc, start=1):
            finder = page.find_tables()
            if not finder.tables:
                continue
            page_tables = []
            for tbl in finder.tables:
                rows = tbl.extract()  # list[list[str | None]]
                rows = [[(c or "").strip() for c in row] for row in rows]
                header = tbl.header.names if tbl.header and not tbl.header.external else None
                page_tables.append({
                    "bbox": tuple(tbl.bbox),
                    "header": header,
                    "rows": rows,
                })
            pages.append({"page_number": page_num, "tables": page_tables})
    return pages
```

- [ ] **Step 4: Run — expect pass**

Run: `uv run pytest tests/test_services/test_pdf_service.py -v -k extract_tables`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/pdf_service.py tests/test_services/test_pdf_service.py
git commit -m "feat: add PDFService.extract_tables using PyMuPDF.find_tables"
```

---

## Task 6: TableChunker — emit table_row + table_whole chunks

**Files:**
- Create: `app/services/table_chunker.py`
- Create: `tests/test_services/test_table_chunker.py`

`TableChunker` takes the output of `PDFService.extract_tables()` and produces the union of:
- one `table_whole` chunk per table (markdown rendering of full grid)
- one `table_row` chunk per non-header row (text format: `[Section: X] [Table: Y] {col}: {val} | ...`)

Both chunk kinds carry `table_id` (a hash of pdf path + table index) so a relevance grader can pull the parent table when a row is ambiguous.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_services/test_table_chunker.py`:

```python
# tests/test_services/test_table_chunker.py
from app.services.table_chunker import TableChunker


def test_chunk_tables_emits_one_whole_and_one_row_per_data_row():
    table_pages = [{
        "page_number": 7,
        "tables": [{
            "bbox": (50.0, 100.0, 400.0, 300.0),
            "header": ["Bolt", "Torque (Nm)"],
            "rows": [
                ["Bolt", "Torque (Nm)"],   # header row repeated as first data row
                ["Cylinder head", "129"],
                ["Valve cover", "10"],
            ],
        }],
    }]
    chunks = TableChunker().chunk_tables(table_pages, base_chunk_index=0, section_titles_by_page={7: "TORQUE SPECS"})

    kinds = [c["chunk_kind"] for c in chunks]
    assert kinds.count("table_whole") == 1
    assert kinds.count("table_row") == 2  # header row dropped

    whole = next(c for c in chunks if c["chunk_kind"] == "table_whole")
    assert whole["page_number"] == 7
    assert "Cylinder head" in whole["content"]
    assert "129" in whole["content"]
    assert whole["section_title"] == "TORQUE SPECS"

    rows = [c for c in chunks if c["chunk_kind"] == "table_row"]
    assert any("Cylinder head" in r["content"] and "129" in r["content"] for r in rows)
    assert all(r["table_id"] == whole["table_id"] for r in rows)


def test_chunk_tables_handles_missing_header_by_using_index_columns():
    table_pages = [{
        "page_number": 1,
        "tables": [{
            "bbox": (0, 0, 100, 100),
            "header": None,
            "rows": [
                ["a", "1"],
                ["b", "2"],
            ],
        }],
    }]
    chunks = TableChunker().chunk_tables(table_pages, base_chunk_index=10, section_titles_by_page={})

    rows = [c for c in chunks if c["chunk_kind"] == "table_row"]
    assert len(rows) == 2
    assert rows[0]["chunk_index"] >= 10
    # When header is unknown, fall back to col_1, col_2…
    assert "col_1" in rows[0]["content"]
    assert "col_2" in rows[0]["content"]


def test_chunk_tables_returns_table_bboxes_for_prose_exclusion():
    """The chunker also reports per-page table bboxes so prose chunking can skip them."""
    table_pages = [{
        "page_number": 4,
        "tables": [
            {"bbox": (10, 20, 30, 40), "header": ["x"], "rows": [["x"], ["a"]]},
            {"bbox": (50, 60, 70, 80), "header": ["y"], "rows": [["y"], ["b"]]},
        ],
    }]
    chunker = TableChunker()
    chunks = chunker.chunk_tables(table_pages, base_chunk_index=0, section_titles_by_page={})
    bboxes = chunker.bboxes_by_page(table_pages)

    assert bboxes[4] == [(10, 20, 30, 40), (50, 60, 70, 80)]
```

- [ ] **Step 2: Run — expect import failure**

Run: `uv run pytest tests/test_services/test_table_chunker.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Implement TableChunker**

Create `app/services/table_chunker.py`:

```python
# app/services/table_chunker.py
"""Convert PyMuPDF table extractions into RAG chunks.

Each detected table produces:
  - one `table_whole` chunk: the full grid rendered as markdown — for queries
    that need cross-row context (e.g. "what bolts are listed for the head?")
  - one `table_row` chunk per data row, prefixed with the column headers — for
    spec-lookup queries that target a single value (e.g. "head bolt torque").

Both kinds share a stable `table_id` so a downstream component can fetch the
parent table when a row alone is ambiguous.
"""
import hashlib


class TableChunker:
    def chunk_tables(
        self,
        table_pages: list[dict],
        base_chunk_index: int,
        section_titles_by_page: dict[int, str],
    ) -> list[dict]:
        """Convert table data into chunks ready for embedding.

        Args:
            table_pages: Output of PDFService.extract_tables().
            base_chunk_index: Starting chunk_index — table chunks claim a
                contiguous block before prose chunking continues.
            section_titles_by_page: Map page_number -> nearest preceding
                section heading (computed by StructuredChunkingService).

        Returns:
            list of chunk dicts: chunk_index, page_number, section_title,
            content, chunk_kind, table_id, table_type=None (filled by
            MetadataExtractor in a later step).
        """
        chunks: list[dict] = []
        idx = base_chunk_index
        for page in table_pages:
            page_num = page["page_number"]
            section_title = section_titles_by_page.get(page_num)
            for tbl_pos, tbl in enumerate(page["tables"]):
                table_id = self._make_table_id(page_num, tbl_pos, tbl["rows"])
                header = tbl["header"] or [f"col_{i + 1}" for i in range(self._max_cols(tbl["rows"]))]

                # Whole-table chunk first.
                chunks.append({
                    "chunk_index": idx,
                    "page_number": page_num,
                    "section_title": section_title,
                    "content": self._render_markdown(header, tbl["rows"]),
                    "chunk_kind": "table_whole",
                    "table_id": table_id,
                    "table_type": None,
                })
                idx += 1

                # Per-row chunks (skip the header if it duplicates the explicit header).
                for row in tbl["rows"]:
                    if header and row == header:
                        continue
                    chunks.append({
                        "chunk_index": idx,
                        "page_number": page_num,
                        "section_title": section_title,
                        "content": self._render_row(header, row, section_title, table_id),
                        "chunk_kind": "table_row",
                        "table_id": table_id,
                        "table_type": None,
                    })
                    idx += 1
        return chunks

    def bboxes_by_page(self, table_pages: list[dict]) -> dict[int, list[tuple]]:
        """Return per-page list of table bboxes so prose chunking can exclude them."""
        return {
            page["page_number"]: [tbl["bbox"] for tbl in page["tables"]]
            for page in table_pages
        }

    # ── Private helpers ───────────────────────────────────────────────────

    @staticmethod
    def _max_cols(rows: list[list[str]]) -> int:
        return max((len(r) for r in rows), default=0)

    @staticmethod
    def _make_table_id(page_num: int, tbl_pos: int, rows: list[list[str]]) -> str:
        """Stable id keyed on page + position + first row contents."""
        first_row = "|".join(rows[0]) if rows else ""
        digest = hashlib.sha1(f"{page_num}:{tbl_pos}:{first_row}".encode()).hexdigest()[:12]
        return f"t_{digest}"

    @staticmethod
    def _render_markdown(header: list[str], rows: list[list[str]]) -> str:
        """Render the full table as a markdown grid for table_whole chunks."""
        lines = ["| " + " | ".join(header) + " |"]
        lines.append("| " + " | ".join("---" for _ in header) + " |")
        for row in rows:
            if row == header:
                continue
            padded = list(row) + [""] * (len(header) - len(row))
            lines.append("| " + " | ".join(padded) + " |")
        return "\n".join(lines)

    @staticmethod
    def _render_row(
        header: list[str],
        row: list[str],
        section_title: str | None,
        table_id: str,
    ) -> str:
        """Render a single row in a way that survives the embedder's lossy compression."""
        section_prefix = f"[Section: {section_title}] " if section_title else ""
        pairs = []
        for col, val in zip(header, row):
            if val:
                pairs.append(f"{col}: {val}")
        return f"{section_prefix}[Table {table_id}] " + " | ".join(pairs)
```

- [ ] **Step 4: Run the tests — expect pass**

Run: `uv run pytest tests/test_services/test_table_chunker.py -v`
Expected: 3 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/table_chunker.py tests/test_services/test_table_chunker.py
git commit -m "feat: add TableChunker for table_row + table_whole chunks"
```

---

## Task 7: StructuredChunkingService respects table bboxes

**Files:**
- Modify: `app/services/structured_chunking_service.py`
- Modify: `tests/test_services/test_structured_chunking_service.py`

The prose chunker must skip lines that fall inside a table bbox, otherwise table cells leak into prose chunks and we double-index them.

- [ ] **Step 1: Write the failing test**

Append to `tests/test_services/test_structured_chunking_service.py`:

```python
def test_chunk_blocks_excludes_lines_inside_provided_bboxes():
    """Lines whose midpoint sits inside a table bbox must not appear in any prose chunk."""
    pages = [{
        "page_number": 1,
        "blocks": [
            {
                "type": 0,
                "lines": [
                    {"bbox": (10, 10, 200, 25), "spans": [
                        {"text": "INTRODUCTION", "size": 18.0, "flags": 16, "font": "Bold"}
                    ]},
                    {"bbox": (10, 100, 200, 115), "spans": [
                        {"text": "This is body text outside the table.", "size": 12.0, "flags": 0, "font": "Regular"}
                    ]},
                    {"bbox": (10, 200, 200, 215), "spans": [
                        {"text": "Cylinder head 129 Nm", "size": 12.0, "flags": 0, "font": "Regular"}
                    ]},
                ],
            }
        ],
    }]
    from app.services.structured_chunking_service import StructuredChunkingService
    svc = StructuredChunkingService(chunk_size=500, chunk_overlap=0)

    # Table bbox covers y=190..220 → the third line is inside it.
    chunks = svc.chunk_blocks(pages, exclude_bboxes_per_page={1: [(0, 190, 300, 220)]})

    flattened = " ".join(c["content"] for c in chunks)
    assert "body text outside" in flattened
    assert "Cylinder head" not in flattened


def test_chunk_blocks_default_no_exclusion_keeps_existing_behaviour():
    """Calling chunk_blocks without exclude_bboxes_per_page works as before."""
    pages = [{
        "page_number": 1,
        "blocks": [{
            "type": 0,
            "lines": [
                {"bbox": (10, 10, 200, 25), "spans": [
                    {"text": "TITLE", "size": 18.0, "flags": 16, "font": "Bold"}
                ]},
                {"bbox": (10, 30, 200, 45), "spans": [
                    {"text": "body", "size": 12.0, "flags": 0, "font": "Regular"}
                ]},
            ],
        }],
    }]
    from app.services.structured_chunking_service import StructuredChunkingService
    chunks = StructuredChunkingService(chunk_size=500, chunk_overlap=0).chunk_blocks(pages)
    assert len(chunks) == 1
    assert chunks[0]["content"] == "body"
```

- [ ] **Step 2: Run — expect failure**

Run: `uv run pytest tests/test_services/test_structured_chunking_service.py::test_chunk_blocks_excludes_lines_inside_provided_bboxes -v`
Expected: FAIL — `chunk_blocks` doesn't take `exclude_bboxes_per_page`.

- [ ] **Step 3: Implement bbox exclusion**

Edit `app/services/structured_chunking_service.py`. Update `chunk_blocks` signature and `_split_into_sections` to accept and apply the exclusion:

```python
def chunk_blocks(
    self,
    page_blocks: list[dict],
    exclude_bboxes_per_page: dict[int, list[tuple]] | None = None,
) -> list[dict]:
    """Convert per-page block data into section-aware chunks.

    Args:
        page_blocks: Output of PDFService.extract_blocks() —
                     list of {"page_number": int, "blocks": list}
        exclude_bboxes_per_page: Optional map page_number → list of
                     (x0, y0, x1, y1) bboxes whose contents should be skipped
                     (because they're already extracted as table chunks).

    Returns:
        list of {"chunk_index", "page_number", "section_title", "content"}
    """
    body_size = self._detect_body_size(page_blocks)
    sections = self._split_into_sections(page_blocks, body_size, exclude_bboxes_per_page or {})
    return self._sections_to_chunks(sections)
```

Update `_split_into_sections`:

```python
def _split_into_sections(
    self,
    page_blocks: list[dict],
    body_size: float,
    exclude_bboxes_per_page: dict[int, list[tuple]],
) -> list[dict]:
    """Walk all blocks and group text under detected section headings."""
    sections: list[dict] = []
    current_title = ""
    current_content: list[tuple[str, int]] = []  # (text, page_number)

    for page in page_blocks:
        page_num = page["page_number"]
        excludes = exclude_bboxes_per_page.get(page_num, [])
        for block in page["blocks"]:
            for line in block["lines"]:
                if self._line_in_excluded_bbox(line, excludes):
                    continue
                spans = [s for s in line["spans"] if s["text"].strip()]
                if not spans:
                    continue

                line_text = " ".join(s["text"] for s in spans).strip()
                if not line_text:
                    continue

                if self._is_heading(spans, body_size):
                    if current_content:
                        sections.append(
                            {"title": current_title, "content": current_content}
                        )
                    current_title = line_text
                    current_content = []
                else:
                    current_content.append((line_text, page_num))

    if current_content:
        sections.append({"title": current_title, "content": current_content})

    return sections


@staticmethod
def _line_in_excluded_bbox(line: dict, excludes: list[tuple]) -> bool:
    """A line whose midpoint sits inside any excluded bbox is skipped."""
    bbox = line.get("bbox")
    if not bbox or not excludes:
        return False
    cx = (bbox[0] + bbox[2]) / 2
    cy = (bbox[1] + bbox[3]) / 2
    for x0, y0, x1, y1 in excludes:
        if x0 <= cx <= x1 and y0 <= cy <= y1:
            return True
    return False
```

- [ ] **Step 4: Run the suite**

Run: `uv run pytest tests/test_services/test_structured_chunking_service.py -v`
Expected: all PASS (existing tests unaffected, new tests pass).

- [ ] **Step 5: Commit**

```bash
git add app/services/structured_chunking_service.py tests/test_services/test_structured_chunking_service.py
git commit -m "feat: StructuredChunkingService skips lines inside provided table bboxes"
```

---

## Task 8: MetadataExtractor — engine_variant + table_type

**Files:**
- Create: `app/services/metadata_extractor.py`
- Create: `tests/test_services/test_metadata_extractor.py`

Per the spec, two-pass classifier:
1. **Filename regex** for `4.2L`, `6.0L`, `5.2L`, `W12` — catches ~90% of the Audi corpus.
2. **LLM fallback** when filename is ambiguous — `gemma4:e4b` reads a chunk sample and picks one of `4.2L | 6.0L | 5.2L | W12 | both | unknown`.

`table_type` is keyword-based on header text: `torque`, `fluid`, `electrical`, `fitment`, `dtc`.

The extractor caches at the *document* level — one classification per PDF, applied to all chunks.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_services/test_metadata_extractor.py`:

```python
# tests/test_services/test_metadata_extractor.py
from unittest.mock import MagicMock
from app.services.ollama_service import OllamaService
from app.services.metadata_extractor import MetadataExtractor


def test_extract_engine_variant_from_filename_regex():
    ollama = MagicMock(spec=OllamaService)
    extractor = MetadataExtractor(ollama, model="m")
    assert extractor.extract_engine_variant(
        filename="15-ENGINE-CYLINDER HEAD,VALVETRAIN 4.2L.pdf",
        sample_text="cylinder head torque...",
    ) == "4.2L"
    ollama.chat.assert_not_called()


def test_extract_engine_variant_handles_w12_pattern():
    ollama = MagicMock(spec=OllamaService)
    extractor = MetadataExtractor(ollama, model="m")
    assert extractor.extract_engine_variant(
        filename="13-ENGINE BLOCK W12.pdf",
        sample_text="...",
    ) == "W12"


def test_extract_engine_variant_falls_back_to_llm_when_filename_ambiguous():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = '{"engine_variant": "4.2L"}'
    extractor = MetadataExtractor(ollama, model="gemma4:e4b")
    result = extractor.extract_engine_variant(
        filename="01-MAINTENANCE.pdf",
        sample_text="Drain the engine oil. Use 0W-30 for the 4.2L V8...",
    )
    assert result == "4.2L"
    ollama.chat.assert_called_once()


def test_extract_engine_variant_returns_none_when_llm_says_unknown():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = '{"engine_variant": "unknown"}'
    extractor = MetadataExtractor(ollama, model="gemma4:e4b")
    assert extractor.extract_engine_variant(
        filename="GLOSSARY.pdf",
        sample_text="general definitions",
    ) is None


def test_extract_engine_variant_recovers_from_malformed_llm_output():
    ollama = MagicMock(spec=OllamaService)
    ollama.chat.return_value = "well, it looks like 6.0L mostly"
    extractor = MetadataExtractor(ollama, model="m")
    # Permissive parse: scan the text for a known variant token.
    assert extractor.extract_engine_variant(
        filename="01-MAINTENANCE.pdf",
        sample_text="anything",
    ) == "6.0L"


def test_classify_table_type_uses_header_keywords():
    ollama = MagicMock(spec=OllamaService)
    extractor = MetadataExtractor(ollama, model="m")
    assert extractor.classify_table_type(
        section_title="TIGHTENING TORQUES",
        header=["Bolt", "Torque (Nm)"],
    ) == "torque"
    assert extractor.classify_table_type(
        section_title="FLUID CAPACITIES",
        header=["System", "Capacity (L)"],
    ) == "fluid"
    assert extractor.classify_table_type(
        section_title="DTC INDEX",
        header=["DTC", "Description"],
    ) == "dtc"
    assert extractor.classify_table_type(
        section_title="MISC",
        header=["A", "B"],
    ) is None
```

- [ ] **Step 2: Run — expect import failure**

Run: `uv run pytest tests/test_services/test_metadata_extractor.py -v`
Expected: FAIL.

- [ ] **Step 3: Implement MetadataExtractor**

Create `app/services/metadata_extractor.py`:

```python
# app/services/metadata_extractor.py
"""Engine-variant + table-type classifier for chunk metadata.

Engine variant is determined per-document (cached) via a two-pass strategy:
filename regex first, LLM fallback when the filename is ambiguous. Table type
is determined per-table from section heading + column header keywords — no
LLM call needed.
"""
import json
import re

from app.services.ollama_service import OllamaService


_VARIANT_REGEX = re.compile(r"\b(4\.2L|6\.0L|5\.2L|W12)\b", re.IGNORECASE)
_VARIANT_NORMALIZE = {"w12": "W12", "4.2l": "4.2L", "6.0l": "6.0L", "5.2l": "5.2L"}

_TABLE_TYPE_KEYWORDS = {
    "torque": ("torque", "tightening", " nm", "n·m", "ft-lb"),
    "fluid": ("fluid", "capacity", "oil", "coolant", "lubricant"),
    "electrical": ("fuse", "amp", "ampere", "voltage", "wiring", "relay"),
    "fitment": ("fitment", "track width", "wheelbase", "diameter", "wear limit"),
    "dtc": ("dtc", "diagnostic trouble", "fault code", "p0", "p1"),
}


class MetadataExtractor:
    def __init__(self, ollama: OllamaService, model: str) -> None:
        self._ollama = ollama
        self._model = model

    def extract_engine_variant(self, filename: str, sample_text: str) -> str | None:
        """Return canonical engine variant tag or None if unknown.

        Filename regex first; LLM fallback if no match. The LLM returns JSON
        `{engine_variant: "4.2L" | "6.0L" | "5.2L" | "W12" | "both" | "unknown"}`.
        Permissively scans free-form output for the same tokens on parse failure.
        """
        match = _VARIANT_REGEX.search(filename)
        if match:
            return _VARIANT_NORMALIZE[match.group(1).lower()]

        # Filename ambiguous → ask the small model.
        prompt = (
            "You classify automotive service-manual content by engine variant.\n\n"
            f"Filename: {filename}\n\n"
            "Content sample:\n"
            f"{sample_text[:1500]}\n\n"
            "Reply with a single JSON object:\n"
            '{"engine_variant": "4.2L" | "6.0L" | "5.2L" | "W12" | "both" | "unknown"}\n'
            "Use 'both' only if the content explicitly applies to multiple engines. "
            "Use 'unknown' if the content does not specify."
        )
        response = self._ollama.chat([{"role": "user", "content": prompt}], self._model)

        # Strict JSON parse.
        try:
            parsed = json.loads(response)
            value = parsed.get("engine_variant", "").lower()
            if value in _VARIANT_NORMALIZE:
                return _VARIANT_NORMALIZE[value]
            if value == "both":
                return "both"
            if value == "unknown":
                return None
        except (json.JSONDecodeError, AttributeError):
            pass

        # Permissive fallback: scan free-form text for a variant token.
        match = _VARIANT_REGEX.search(response)
        if match:
            return _VARIANT_NORMALIZE[match.group(1).lower()]
        return None

    def classify_table_type(self, section_title: str | None, header: list[str]) -> str | None:
        """Return one of `torque | fluid | electrical | fitment | dtc | None`."""
        haystack = " ".join([section_title or "", *header]).lower()
        for table_type, keywords in _TABLE_TYPE_KEYWORDS.items():
            if any(kw in haystack for kw in keywords):
                return table_type
        return None
```

- [ ] **Step 4: Run the tests — expect pass**

Run: `uv run pytest tests/test_services/test_metadata_extractor.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add app/services/metadata_extractor.py tests/test_services/test_metadata_extractor.py
git commit -m "feat: add MetadataExtractor for engine_variant + table_type"
```

---

## Task 9: DocumentService integrates table chunker + metadata + new repo signature

**Files:**
- Modify: `app/services/document_service.py`
- Modify: `tests/test_services/test_document_service.py`

Pipeline order matches the spec: PDF → tables + table_bboxes → prose (excluding bboxes) → metadata → contextualization → embedding → bulk_create.

- [ ] **Step 1: Look at the current document service test for orientation**

Read `tests/test_services/test_document_service.py` to remember the mock fixture pattern. We'll heavily revise it.

- [ ] **Step 2: Replace the document service test**

Replace `tests/test_services/test_document_service.py`:

```python
# tests/test_services/test_document_service.py
import pytest
from unittest.mock import MagicMock

from app.repositories.vehicle_repository import VehicleRepository
from app.repositories.document_repository import DocumentRepository
from app.repositories.chunk_repository import ChunkRepository, ChunkInsert
from app.services.contextualization_service import ContextualizationService
from app.services.document_service import DocumentService
from app.services.embedding_service import EmbeddingService
from app.services.metadata_extractor import MetadataExtractor
from app.services.pdf_service import PDFService
from app.services.structured_chunking_service import StructuredChunkingService
from app.services.table_chunker import TableChunker


@pytest.fixture
def vehicle(db_session):
    v = VehicleRepository(db_session).create(year=2006, make="Audi", model="A8", engine="4.2L V8")
    db_session.flush()
    return v


def _make_pdf(tmp_path):
    p = tmp_path / "manual.pdf"
    p.write_bytes(b"%PDF-1.4\n%fake\n")  # contents irrelevant — PDFService is mocked
    return str(p)


def _make_service(db_session, tmp_path, **overrides):
    pdf_service = overrides.get("pdf_service") or MagicMock(spec=PDFService)
    chunking_service = overrides.get("chunking_service") or MagicMock(spec=StructuredChunkingService)
    table_chunker = overrides.get("table_chunker") or MagicMock(spec=TableChunker)
    contextualization_service = overrides.get("contextualization_service") or MagicMock(spec=ContextualizationService)
    embedding_service = overrides.get("embedding_service") or MagicMock(spec=EmbeddingService)
    metadata_extractor = overrides.get("metadata_extractor") or MagicMock(spec=MetadataExtractor)

    return DocumentService(
        doc_repo=DocumentRepository(db_session),
        chunk_repo=ChunkRepository(db_session),
        pdf_service=pdf_service,
        chunking_service=chunking_service,
        table_chunker=table_chunker,
        contextualization_service=contextualization_service,
        embedding_service=embedding_service,
        metadata_extractor=metadata_extractor,
        docs_dir=str(tmp_path / "docs"),
    )


def test_add_document_runs_table_then_prose_then_metadata_then_embed(db_session, vehicle, tmp_path):
    pdf_path = _make_pdf(tmp_path)

    pdf_service = MagicMock(spec=PDFService)
    pdf_service.extract_blocks.return_value = [{"page_number": 1, "blocks": []}]
    pdf_service.extract_tables.return_value = [{
        "page_number": 1,
        "tables": [{"bbox": (0, 0, 100, 100), "header": ["Bolt", "Nm"], "rows": [["Bolt", "Nm"], ["Head", "129"]]}],
    }]

    table_chunker = MagicMock(spec=TableChunker)
    table_chunker.chunk_tables.return_value = [
        {"chunk_index": 0, "page_number": 1, "section_title": "TORQUE",
         "content": "| Bolt | Nm |\n| --- | --- |\n| Head | 129 |",
         "chunk_kind": "table_whole", "table_id": "t_abc", "table_type": None},
        {"chunk_index": 1, "page_number": 1, "section_title": "TORQUE",
         "content": "[Section: TORQUE] [Table t_abc] Bolt: Head | Nm: 129",
         "chunk_kind": "table_row", "table_id": "t_abc", "table_type": None},
    ]
    table_chunker.bboxes_by_page.return_value = {1: [(0, 0, 100, 100)]}

    chunking_service = MagicMock(spec=StructuredChunkingService)
    chunking_service.chunk_blocks.return_value = [
        {"chunk_index": 2, "page_number": 1, "section_title": None, "content": "prose body"},
    ]

    metadata = MagicMock(spec=MetadataExtractor)
    metadata.extract_engine_variant.return_value = "4.2L"
    metadata.classify_table_type.return_value = "torque"

    contextualization = MagicMock(spec=ContextualizationService)
    contextualization.generate_context.side_effect = lambda **_: "ctx"

    embedding = MagicMock(spec=EmbeddingService)
    embedding.embed_texts.return_value = [[0.1] * 4, [0.2] * 4, [0.3] * 4]

    svc = _make_service(
        db_session, tmp_path,
        pdf_service=pdf_service,
        chunking_service=chunking_service,
        table_chunker=table_chunker,
        contextualization_service=contextualization,
        embedding_service=embedding,
        metadata_extractor=metadata,
    )

    doc = svc.add_document(vehicle_id=vehicle.id, pdf_path=pdf_path)
    db_session.flush()

    # Prose chunker received the table bboxes for exclusion.
    call_kwargs = chunking_service.chunk_blocks.call_args.kwargs
    assert call_kwargs.get("exclude_bboxes_per_page") == {1: [(0, 0, 100, 100)]}

    # All three chunk kinds persisted.
    rows = ChunkRepository(db_session).list_by_vehicle(vehicle.id)
    kinds = sorted(r.chunk_kind for r in rows)
    assert kinds == ["prose", "table_row", "table_whole"]

    # Engine variant + table_type populated.
    table_rows = [r for r in rows if r.chunk_kind in ("table_row", "table_whole")]
    assert all(r.engine_variant == "4.2L" for r in table_rows)
    assert all(r.table_type == "torque" for r in table_rows)
    prose = [r for r in rows if r.chunk_kind == "prose"]
    assert all(r.engine_variant == "4.2L" for r in prose)
    assert all(r.table_type is None for r in prose)


def test_add_document_marks_failed_on_exception(db_session, vehicle, tmp_path):
    pdf_path = _make_pdf(tmp_path)

    pdf_service = MagicMock(spec=PDFService)
    pdf_service.extract_blocks.side_effect = RuntimeError("boom")

    svc = _make_service(db_session, tmp_path, pdf_service=pdf_service)

    with pytest.raises(RuntimeError, match="Document processing failed"):
        svc.add_document(vehicle_id=vehicle.id, pdf_path=pdf_path)

    docs = DocumentRepository(db_session).list_by_vehicle(vehicle.id)
    assert len(docs) == 1
    assert docs[0].processing_status == "failed"


def test_add_document_raises_when_pdf_missing(db_session, vehicle, tmp_path):
    svc = _make_service(db_session, tmp_path)
    with pytest.raises(FileNotFoundError):
        svc.add_document(vehicle_id=vehicle.id, pdf_path="/no/such/file.pdf")
```

- [ ] **Step 3: Run — expect failure (signature mismatch)**

Run: `uv run pytest tests/test_services/test_document_service.py -v`
Expected: FAIL.

- [ ] **Step 4: Update DocumentService**

Replace `app/services/document_service.py`:

```python
# app/services/document_service.py
import shutil
from pathlib import Path

from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.repositories.chunk_repository import ChunkInsert, ChunkRepository
from app.repositories.document_repository import DocumentRepository
from app.services.contextualization_service import ContextualizationService
from app.services.embedding_service import EmbeddingService
from app.services.metadata_extractor import MetadataExtractor
from app.services.pdf_service import PDFService
from app.services.structured_chunking_service import StructuredChunkingService
from app.services.table_chunker import TableChunker
from app.utils.paths import get_document_path


class DocumentService:
    def __init__(
        self,
        doc_repo: DocumentRepository,
        chunk_repo: ChunkRepository,
        pdf_service: PDFService,
        chunking_service: StructuredChunkingService,
        table_chunker: TableChunker,
        contextualization_service: ContextualizationService,
        embedding_service: EmbeddingService,
        metadata_extractor: MetadataExtractor,
        docs_dir: str,
    ) -> None:
        self._doc_repo = doc_repo
        self._chunk_repo = chunk_repo
        self._pdf_service = pdf_service
        self._chunking_service = chunking_service
        self._table_chunker = table_chunker
        self._contextualization_service = contextualization_service
        self._embedding_service = embedding_service
        self._metadata_extractor = metadata_extractor
        self._docs_dir = docs_dir

    def add_document(
        self,
        vehicle_id: int,
        pdf_path: str,
        document_type: str = "service_manual",
    ) -> Document:
        source = Path(pdf_path)
        if not source.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        doc = self._doc_repo.create(
            vehicle_id=vehicle_id,
            file_name=source.name,
            stored_path="",
            document_type=document_type,
        )
        self._doc_repo.session.flush()

        dest = get_document_path(self._docs_dir, vehicle_id, doc.id, source.name)
        dest.parent.mkdir(parents=True, exist_ok=True)

        try:
            shutil.copy2(source, dest)
            doc.stored_path = str(dest)

            # 1. Extract blocks + tables.
            page_blocks = self._pdf_service.extract_blocks(str(dest))
            table_pages = self._pdf_service.extract_tables(str(dest))

            # 2. Section title map for table chunks (best-effort: use the
            # section detected per-page by the structured chunker on its
            # first pass over the page so table chunks share section titles
            # with surrounding prose). Compute by running the prose chunker
            # without exclusions — cheap, doesn't reach the embedder.
            section_titles_by_page = self._extract_section_titles(page_blocks)
            exclude_bboxes = self._table_chunker.bboxes_by_page(table_pages)

            # 3. Build raw chunks: tables first (claim chunk indices 0..N), prose after.
            table_chunks = self._table_chunker.chunk_tables(
                table_pages,
                base_chunk_index=0,
                section_titles_by_page=section_titles_by_page,
            )
            base_idx_for_prose = (
                max((c["chunk_index"] for c in table_chunks), default=-1) + 1
            )
            prose_chunks_raw = self._chunking_service.chunk_blocks(
                page_blocks, exclude_bboxes_per_page=exclude_bboxes
            )
            prose_chunks = [
                {**c, "chunk_index": base_idx_for_prose + i, "chunk_kind": "prose",
                 "table_id": None, "table_type": None}
                for i, c in enumerate(prose_chunks_raw)
            ]
            raw_chunks = table_chunks + prose_chunks

            # 4. Engine variant — once per document.
            sample_text = "\n".join(c["content"] for c in raw_chunks[:5])
            engine_variant = self._metadata_extractor.extract_engine_variant(
                filename=source.name, sample_text=sample_text,
            )

            # 5. Table type — per chunk for table_* kinds.
            for c in raw_chunks:
                if c["chunk_kind"] in ("table_row", "table_whole"):
                    header = self._extract_header(c["content"])
                    c["table_type"] = self._metadata_extractor.classify_table_type(
                        section_title=c.get("section_title"), header=header,
                    )

            # 6. Contextualize.
            total = len(raw_chunks)
            contexts = [
                self._contextualization_service.generate_context(
                    chunk_content=c["content"],
                    filename=source.name,
                    page_number=c.get("page_number"),
                    section_title=c.get("section_title"),
                    chunk_index=c["chunk_index"],
                    total_chunks=total,
                )
                for c in raw_chunks
            ]

            # 7. Build embedding inputs (also the FTS5-indexed text).
            indexable_texts = [
                (
                    f"Document: {source.name} | "
                    f"Section: {c.get('section_title') or 'Unknown'} | "
                    f"Page: {c.get('page_number', 'unknown')}\n"
                    f"{ctx}\n\n{c['content']}"
                )
                for c, ctx in zip(raw_chunks, contexts)
            ]
            embeddings = self._embedding_service.embed_texts(indexable_texts)

            # 8. Persist to all three tables.
            self._chunk_repo.bulk_create([
                ChunkInsert(
                    chunk=DocumentChunk(
                        document_id=doc.id,
                        chunk_index=c["chunk_index"],
                        page_number=c.get("page_number"),
                        section_title=c.get("section_title"),
                        content=c["content"],
                        context_summary=ctx,
                        chunk_kind=c["chunk_kind"],
                        engine_variant=engine_variant,
                        table_type=c.get("table_type"),
                        table_id=c.get("table_id"),
                    ),
                    indexable_text=text,
                    embedding=emb,
                )
                for c, ctx, text, emb in zip(raw_chunks, contexts, indexable_texts, embeddings)
            ])

            self._doc_repo.update_status(doc.id, "ready")
        except Exception as exc:
            self._doc_repo.update_status(doc.id, "failed")
            raise RuntimeError(f"Document processing failed: {exc}") from exc

        return doc

    def list_documents(self, vehicle_id: int) -> list[Document]:
        return self._doc_repo.list_by_vehicle(vehicle_id)

    # ── Private helpers ──────────────────────────────────────────────────

    def _extract_section_titles(self, page_blocks: list[dict]) -> dict[int, str]:
        """Best-effort: nearest preceding section heading per page."""
        titles_by_page: dict[int, str] = {}
        chunks = self._chunking_service.chunk_blocks(page_blocks)
        for chunk in chunks:
            page = chunk.get("page_number")
            title = chunk.get("section_title")
            if page is not None and title and page not in titles_by_page:
                titles_by_page[page] = title
        return titles_by_page

    @staticmethod
    def _extract_header(content: str) -> list[str]:
        """Pull the column headers out of a markdown or row-format table chunk."""
        # Markdown: first line `| col1 | col2 |`
        if content.startswith("|"):
            first_line = content.splitlines()[0]
            return [c.strip() for c in first_line.strip().strip("|").split("|") if c.strip()]
        # Row format: `[Section: ...] [Table ...] col1: val | col2: val`
        if "|" in content:
            cells = content.split("|")
            return [c.split(":")[0].strip() for c in cells if ":" in c]
        return []
```

- [ ] **Step 5: Run document service tests — expect pass**

Run: `uv run pytest tests/test_services/test_document_service.py -v`
Expected: 3 PASS.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest tests/ -v`
Expected: green (with the two skipped retrieval/chat files).

- [ ] **Step 7: Commit**

```bash
git add app/services/document_service.py tests/test_services/test_document_service.py
git commit -m "feat: integrate TableChunker + MetadataExtractor into DocumentService"
```

---

## Task 10: CLI wiring + db reset + recursive document add

**Files:**
- Modify: `app/cli.py`

The CLI changes:
1. `_make_document_service` constructs the new dependencies.
2. New `db reset` command that drops `data/app.db` and `data/documents/*`.
3. `document add` accepts a directory and recurses into it (Spec issue #2).

- [ ] **Step 1: Update _make_document_service**

In `app/cli.py`, replace `_make_document_service`:

```python
def _make_document_service(session):
    from app.repositories.document_repository import DocumentRepository
    from app.repositories.chunk_repository import ChunkRepository
    from app.services.document_service import DocumentService
    from app.services.pdf_service import PDFService
    from app.services.structured_chunking_service import StructuredChunkingService
    from app.services.table_chunker import TableChunker
    from app.services.contextualization_service import ContextualizationService
    from app.services.embedding_service import EmbeddingService
    from app.services.metadata_extractor import MetadataExtractor
    from app.services.ollama_service import OllamaService

    ollama_svc = OllamaService(settings.ollama_base_url)
    context_svc = ContextualizationService(ollama_svc, settings.context_model)
    embedding_svc = EmbeddingService(ollama_svc, settings.embed_model)
    metadata_svc = MetadataExtractor(ollama_svc, settings.context_model)
    return DocumentService(
        doc_repo=DocumentRepository(session),
        chunk_repo=ChunkRepository(session),
        pdf_service=PDFService(),
        chunking_service=StructuredChunkingService(settings.chunk_size, settings.chunk_overlap),
        table_chunker=TableChunker(),
        contextualization_service=context_svc,
        embedding_service=embedding_svc,
        metadata_extractor=metadata_svc,
        docs_dir=settings.docs_dir,
    )
```

- [ ] **Step 2: Add `db reset` command**

In `app/cli.py`, after the chat_app declarations, add a new sub-app and command:

```python
db_app = typer.Typer(help="Database maintenance.")
app.add_typer(db_app, name="db")


@db_app.command("reset")
def db_reset(
    yes: bool = typer.Option(False, "--yes", "-y", help="Skip confirmation."),
):
    """Drop the SQLite database and stored PDFs (development only)."""
    import shutil

    db_path = Path(settings.db_path)
    docs_dir = Path(settings.docs_dir)

    if not yes:
        console.print(f"[yellow]This will delete:[/yellow]")
        console.print(f"  • {db_path}")
        console.print(f"  • {docs_dir}/* (PDF files)")
        confirm = typer.confirm("Continue?", default=False)
        if not confirm:
            console.print("[dim]Cancelled.[/dim]")
            raise typer.Exit(0)

    if db_path.exists():
        db_path.unlink()
        print_success(f"Deleted {db_path}")
    if docs_dir.exists():
        for child in docs_dir.iterdir():
            if child.name == ".gitkeep":
                continue
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()
        print_success(f"Cleared {docs_dir}/")

    # Reset module-global engine cache so the next command rebuilds it.
    global _engine, _Session
    _engine = None
    _Session = None
```

- [ ] **Step 3: Make `document add` accept a directory**

In `app/cli.py`, replace the `document_add` command:

```python
@document_app.command("add")
def document_add(
    vehicle_id: int,
    pdf_path: str,
    doc_type: str = typer.Option("service_manual", "--type", help="Document type label"),
    recursive: bool = typer.Option(False, "--recursive", "-r", help="Recurse into directories."),
):
    """Upload and process a PDF (or a directory of PDFs) for a vehicle."""
    target = Path(pdf_path)
    if not target.exists():
        print_error(f"Path not found: {pdf_path}")
        raise typer.Exit(1)

    if target.is_dir():
        if not recursive:
            print_error(f"{pdf_path} is a directory — pass --recursive to process all PDFs inside it.")
            raise typer.Exit(1)
        pdf_files = sorted(target.rglob("*.pdf"))
    else:
        pdf_files = [target]

    if not pdf_files:
        print_error(f"No PDFs found at {pdf_path}")
        raise typer.Exit(1)

    failed: list[tuple[str, str]] = []
    for pdf_file in pdf_files:
        with get_session() as session:
            svc = _make_document_service(session)
            try:
                with console.status(f"Processing {pdf_file.name}...", spinner="dots"):
                    doc = svc.add_document(vehicle_id=vehicle_id, pdf_path=str(pdf_file), document_type=doc_type)
                print_success(f"[{doc.id}] {doc.file_name}")
            except (FileNotFoundError, RuntimeError, ValueError) as exc:
                failed.append((pdf_file.name, str(exc)))
                print_error(f"{pdf_file.name}: {exc}")

    if failed:
        console.print(f"\n[red]Completed with {len(failed)} failure(s).[/red]")
        raise typer.Exit(1 if len(failed) == len(pdf_files) else 0)
```

- [ ] **Step 4: Sanity-check the CLI**

Run: `uv run mechanic-sidekick --help`
Expected: shows `db` subcommand.

Run: `uv run mechanic-sidekick db --help`
Expected: shows `reset`.

Run: `uv run mechanic-sidekick db reset --yes` (only if you're OK losing the dev database — you should be, the migration drops chunks anyway).
Expected: `✓ Deleted ./data/app.db` and `✓ Cleared ./data/documents/`. No traceback.

- [ ] **Step 5: Run full suite once more**

Run: `uv run pytest tests/ -v`
Expected: green (with skipped retrieval/chat).

- [ ] **Step 6: Commit**

```bash
git add app/cli.py
git commit -m "feat: wire ingest pipeline; add db reset; recurse into doc dirs"
```

---

## Task 11: End-to-end smoke ingest on a real PDF

**Goal:** Verify the whole pipeline works on real Ollama + a real PDF before declaring Plan 1 done. No code changes — manual verification only.

- [ ] **Step 1: Confirm Ollama is running**

Run: `curl -s http://localhost:11434/api/tags | head -c 200`
Expected: JSON listing local models including `gemma4:e4b` and `qwen3-embedding:4b`.

- [ ] **Step 2: Reset the dev database**

Run: `uv run mechanic-sidekick db reset --yes`
Expected: clean confirmations.

- [ ] **Step 3: Add a test vehicle**

Run: `uv run mechanic-sidekick vehicle add` and respond at the prompts:
- Year: `2006`
- Make: `Audi`
- Model: `A8`
- Engine: `4.2L V8`
- VIN: (skip)
- Notes: (skip)

Expected: `✓ Vehicle added with ID 1`.

- [ ] **Step 4: Ingest one PDF that contains tables**

Pick any Audi 4.2L PDF that has torque tables — e.g. `data/documents/Audi_A8_2004-2009 Manuals/15-ENGINE-CYLINDER HEAD,VALVETRAIN 4.2L.pdf`.

Run:
```bash
uv run mechanic-sidekick document add 1 "data/documents/Audi_A8_2004-2009 Manuals/15-ENGINE-CYLINDER HEAD,VALVETRAIN 4.2L.pdf"
```

Expected: spinner runs through processing (should take 30s-2min depending on length); ends with `✓ [1] 15-ENGINE-CYLINDER HEAD,VALVETRAIN 4.2L.pdf`.

- [ ] **Step 5: Inspect the database**

Run:
```bash
uv run python -c "
from sqlalchemy import text
from app.db import get_engine, Base
import app.models  # noqa
from app.db.migrations import apply_hybrid_retrieval_migration
from app.config import settings

engine = get_engine(f'sqlite:///{settings.db_path}')
with engine.connect() as conn:
    print('chunk_kind counts:')
    for row in conn.execute(text('SELECT chunk_kind, COUNT(*) FROM document_chunks GROUP BY chunk_kind')):
        print(f'  {row[0]}: {row[1]}')
    print('engine_variant counts:')
    for row in conn.execute(text('SELECT engine_variant, COUNT(*) FROM document_chunks GROUP BY engine_variant')):
        print(f'  {row[0]}: {row[1]}')
    print('table_type counts:')
    for row in conn.execute(text(\"SELECT table_type, COUNT(*) FROM document_chunks WHERE table_type IS NOT NULL GROUP BY table_type\")):
        print(f'  {row[0]}: {row[1]}')
    print('FTS5 row count:', conn.execute(text('SELECT COUNT(*) FROM document_chunks_fts')).scalar())
    print('vec0 row count:', conn.execute(text('SELECT COUNT(*) FROM document_chunks_vec')).scalar())
"
```

Expected output (numbers will vary):
```
chunk_kind counts:
  prose: 28
  table_row: 14
  table_whole: 4
engine_variant counts:
  4.2L: 46
table_type counts:
  torque: 18
FTS5 row count: 46
vec0 row count: 46
```

The key invariants: prose + table_row + table_whole are all present; engine_variant is `4.2L` for everything (filename had `4.2L`); FTS5 and vec0 row counts equal the main chunk count.

- [ ] **Step 6: Verify FTS5 actually searches**

Run:
```bash
uv run python -c "
from sqlalchemy import text
from app.db import get_engine
from app.config import settings

engine = get_engine(f'sqlite:///{settings.db_path}')
with engine.connect() as conn:
    rows = conn.execute(text(\"SELECT chunk_id, snippet(document_chunks_fts, 1, '<<', '>>', '...', 16) FROM document_chunks_fts WHERE document_chunks_fts MATCH 'torque' LIMIT 3\")).fetchall()
    for r in rows: print(r)
"
```

Expected: 3 rows matching "torque" with the term highlighted in `<<>>`. Confirms FTS5 indexed the chunks.

- [ ] **Step 7: Verify vec0 cosine search works**

Run:
```bash
uv run python -c "
import struct
from sqlalchemy import text
from app.db import get_engine
from app.services.ollama_service import OllamaService
from app.services.embedding_service import EmbeddingService
from app.config import settings

ollama = OllamaService(settings.ollama_base_url)
emb = EmbeddingService(ollama, settings.embed_model).embed_query('cylinder head bolt torque')
buf = struct.pack(f'{len(emb)}f', *emb)

engine = get_engine(f'sqlite:///{settings.db_path}')
with engine.connect() as conn:
    rows = conn.execute(text(
        'SELECT chunk_id, distance FROM document_chunks_vec WHERE embedding MATCH :q AND k = 3 ORDER BY distance'
    ), {'q': buf}).fetchall()
    for r in rows: print(r)
"
```

Expected: 3 rows with `chunk_id` and `distance` (a positive float). Confirms vec0 cosine query works end-to-end.

- [ ] **Step 8: No commit for this task**

This is verification, not code. Move on to Plan 2 once everything above checks out. If anything fails, that's a bug in the prior tasks — fix root cause, don't paper over.

---

## Self-Review Checklist (run before marking Plan 1 done)

- [ ] Spec section 2 (ingest) — every change covered? Yes: TableChunker (Task 6), MetadataExtractor (Task 8), schema migration with FTS5 + vec0 (Task 3), pipeline order in DocumentService (Task 9).
- [ ] Spec section 6 (schema) — `chunk_kind`, `engine_variant`, `table_type`, `table_id` columns? FTS5? vec0? Migration script? `db reset` command? All in Tasks 2, 3, 10.
- [ ] No `embedding_json` references remain except in skipped tests (Plans 2/3 will replace those).
- [ ] No placeholders in any task — every step has either a code block, a command, or an unambiguous prose instruction.
- [ ] Type consistency — `ChunkInsert` fields used in Task 9 (`chunk`, `indexable_text`, `embedding`) match the dataclass in Task 4. `DocumentService.__init__` parameters in Task 9 match the wiring in Task 10.
- [ ] Open spec issue #2 (subdirectory recursion) addressed in Task 10 step 3.
