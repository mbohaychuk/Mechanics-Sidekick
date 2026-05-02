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

    # Seed real chunk data, then re-run the migration. The second call must not delete anything.
    with engine.begin() as conn:
        conn.execute(text(
            "INSERT INTO vehicles (year, make, model, engine, created_utc) "
            "VALUES (2018, 'Ford', 'F-150', '5.0L', '2026-05-02 00:00:00')"
        ))
        conn.execute(text(
            "INSERT INTO documents (vehicle_id, file_name, stored_path, document_type, processing_status, uploaded_utc) "
            "VALUES (1, 'a.pdf', '/tmp/a.pdf', 'service_manual', 'ready', '2026-05-02 00:00:00')"
        ))
        conn.execute(text(
            "INSERT INTO document_chunks (document_id, chunk_index, content, chunk_kind) "
            "VALUES (1, 0, 'real chunk', 'prose')"
        ))

    apply_hybrid_retrieval_migration(engine, vec_dim=4)  # must not raise AND must not delete

    with engine.connect() as conn:
        row_count = conn.execute(text("SELECT COUNT(*) FROM document_chunks")).scalar()
        assert row_count == 1, "Second migration call must be a no-op — it must not delete chunks"


def test_migration_drops_existing_chunks(tmp_path):
    db_url = f"sqlite:///{tmp_path / 'test.db'}"
    engine = get_engine(db_url)
    Base.metadata.create_all(engine)

    # Simulate the legacy schema: add the embedding_json column the new model dropped.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE document_chunks ADD COLUMN embedding_json TEXT"))

    with engine.connect() as conn:
        conn.execute(text("INSERT INTO vehicles (year, make, model, engine, created_utc) VALUES (2018, 'Ford', 'F-150', '5.0L', '2018-01-01T00:00:00')"))
        conn.execute(text(
            "INSERT INTO documents (vehicle_id, file_name, stored_path, document_type, processing_status, uploaded_utc) "
            "VALUES (1, 'a.pdf', '/tmp/a.pdf', 'service_manual', 'ready', '2018-01-01T00:00:00')"
        ))
        conn.execute(text(
            "INSERT INTO document_chunks (document_id, chunk_index, content, chunk_kind) VALUES (1, 0, 'old', 'prose')"
        ))
        conn.commit()

    apply_hybrid_retrieval_migration(engine, vec_dim=4)

    with engine.connect() as conn:
        row_count = conn.execute(text("SELECT COUNT(*) FROM document_chunks")).scalar()
        assert row_count == 0
