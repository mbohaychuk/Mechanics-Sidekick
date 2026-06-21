import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError

from app.db import Base, ensure_runtime_columns
from app.models.job import Job
from app.models.vehicle import Vehicle


def test_ensure_runtime_columns_adds_missing_columns_to_old_db(tmp_path):
    # Simulate a pre-release DB: create the documents table WITHOUT the new chunk columns,
    # then assert the additive migration adds them idempotently (no migration framework yet).
    engine = create_engine(f"sqlite:///{tmp_path/'old.db'}")
    with engine.begin() as conn:
        conn.execute(text(
            "CREATE TABLE documents (id INTEGER PRIMARY KEY, vehicle_id INTEGER, file_name TEXT, "
            "stored_path TEXT, document_type TEXT, uploaded_utc TEXT, processing_status TEXT)"
        ))

    ensure_runtime_columns(engine)
    cols = {c["name"] for c in inspect(engine).get_columns("documents")}
    assert {"chunks_total", "chunks_done"} <= cols

    ensure_runtime_columns(engine)  # idempotent: a second run is a no-op
    assert {c["name"] for c in inspect(engine).get_columns("documents")} == cols


def test_deleting_a_vehicle_cascades_to_its_jobs(db_session):
    # ON DELETE CASCADE (with FK enforcement on) cleans up children instead of orphaning them.
    v = Vehicle(year=2020, make="Test", model="X", engine="2.0L")
    db_session.add(v)
    db_session.flush()
    db_session.add(Job(vehicle_id=v.id, title="job"))
    db_session.flush()

    db_session.delete(v)
    db_session.flush()

    assert db_session.query(Job).filter_by(vehicle_id=v.id).count() == 0


def test_foreign_keys_are_enforced(db_session):
    # SQLite ships with FK enforcement OFF; the app must turn it ON or the relational
    # schema is decorative. A job referencing a nonexistent vehicle must be rejected.
    db_session.add(Job(vehicle_id=9999, title="orphan job"))
    with pytest.raises(IntegrityError):
        db_session.flush()
