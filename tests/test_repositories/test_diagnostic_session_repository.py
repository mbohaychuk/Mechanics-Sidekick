import json

from app.models.vehicle import Vehicle
from app.repositories.diagnostic_session_repository import DiagnosticSessionRepository


def _vehicle(db_session):
    v = Vehicle(year=2004, make="Audi", model="A8", engine="4.2L", vin="WAUZZZ")
    db_session.add(v)
    db_session.commit()
    return v.id


def test_create_then_complete(db_session):
    vid = _vehicle(db_session)
    repo = DiagnosticSessionRepository(db_session)
    row = repo.create(vehicle_id=vid, live_session_id=None, protocol_name="default")
    db_session.commit()
    assert row.id is not None
    assert row.status == "running"

    report = {"overall_status": "fair", "summary": "ok", "findings": []}
    repo.complete(
        row.id, overall_status="fair", summary="ok",
        report_json=json.dumps(report), commentary_json=json.dumps([{"t": 0, "text": "hi"}]),
    )
    db_session.commit()
    fetched = repo.get_by_id(row.id)
    assert fetched.status == "completed"
    assert fetched.overall_status == "fair"
    assert fetched.ended_utc is not None
    assert json.loads(fetched.report_json)["summary"] == "ok"


def test_mark_error_and_list_newest_first(db_session):
    vid = _vehicle(db_session)
    repo = DiagnosticSessionRepository(db_session)
    a = repo.create(vehicle_id=vid, live_session_id=None, protocol_name="default")
    db_session.commit()
    b = repo.create(vehicle_id=vid, live_session_id=None, protocol_name="default")
    db_session.commit()
    repo.mark_error(a.id)
    db_session.commit()

    rows = repo.list_by_vehicle(vid)
    assert [r.id for r in rows] == [b.id, a.id]  # newest first
    assert repo.get_by_id(a.id).status == "error"
    assert repo.list_by_vehicle(vid, limit=1) == [rows[0]]


def test_status_filter_applied_before_limit(db_session):
    """SQL status filter must run before LIMIT so older completed rows aren't silently dropped."""
    vid = _vehicle(db_session)
    repo = DiagnosticSessionRepository(db_session)

    # Three newest rows: running, error, running (non-completed)
    for _ in range(2):
        repo.create(vehicle_id=vid, live_session_id=None, protocol_name="default")
        db_session.commit()
    err = repo.create(vehicle_id=vid, live_session_id=None, protocol_name="default")
    db_session.commit()
    repo.mark_error(err.id)
    db_session.commit()

    # Oldest row: completed
    oldest = repo.create(vehicle_id=vid, live_session_id=None, protocol_name="default")
    db_session.commit()
    # Re-fetch; create returns the ORM object but we need to complete it via id
    repo.complete(
        oldest.id, overall_status="good", summary="all clear",
        report_json=json.dumps({"findings": []}), commentary_json="[]",
    )
    db_session.commit()

    # With limit=3 and no filter the oldest completed row would be cut off; with status filter it must appear.
    rows = repo.list_by_vehicle(vid, limit=3, status="completed")
    assert len(rows) == 1
    assert rows[0].id == oldest.id
    assert rows[0].status == "completed"
