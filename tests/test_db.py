import pytest
from sqlalchemy.exc import IntegrityError

from app.models.job import Job
from app.models.vehicle import Vehicle


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
