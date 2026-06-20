import pytest
from sqlalchemy.exc import IntegrityError

from app.models.job import Job


def test_foreign_keys_are_enforced(db_session):
    # SQLite ships with FK enforcement OFF; the app must turn it ON or the relational
    # schema is decorative. A job referencing a nonexistent vehicle must be rejected.
    db_session.add(Job(vehicle_id=9999, title="orphan job"))
    with pytest.raises(IntegrityError):
        db_session.flush()
