import json

from app.models.vehicle import Vehicle
from app.repositories.live_session_repository import LiveSessionRepository
from app.repositories.live_sample_repository import LiveSampleRepository


def _vehicle(db_session, vin="WAUZZZ"):
    v = Vehicle(year=2004, make="Audi", model="A8", engine="4.2L", vin=vin)
    db_session.add(v)
    db_session.flush()
    return v.id


def test_session_create_end_and_latest_pids(db_session):
    vid = _vehicle(db_session)
    repo = LiveSessionRepository(db_session)

    s = repo.create(vehicle_id=vid, vin="WAUZZZ", target_hz=1.0, pids=["RPM", "SPEED"])
    db_session.flush()
    assert s.id is not None
    assert s.status == "recording"
    assert json.loads(s.pids_json) == ["RPM", "SPEED"]

    repo.mark_ended(s.id, status="ended", achieved_hz=0.8, sample_count=12)
    again = repo.get_by_id(s.id)
    assert again.status == "ended"
    assert again.ended_utc is not None
    assert again.achieved_hz == 0.8
    assert again.sample_count == 12

    assert repo.latest_pids(vid) == ["RPM", "SPEED"]
    assert [x.id for x in repo.list_by_vehicle(vid)] == [s.id]


def test_sample_bulk_create_and_list(db_session):
    vid = _vehicle(db_session)
    s = LiveSessionRepository(db_session).create(vehicle_id=vid, vin=None, target_hz=1.0, pids=["RPM"])
    db_session.flush()

    samples = LiveSampleRepository(db_session)
    samples.bulk_create([
        {"session_id": s.id, "seq": 1, "t_offset_ms": 0, "values": {"RPM": {"value": 800, "unit": "rpm"}}},
        {"session_id": s.id, "seq": 2, "t_offset_ms": 1000, "values": {"RPM": {"value": 820, "unit": "rpm"}}},
    ])
    db_session.flush()

    rows = samples.list_by_session(s.id)
    assert [r.seq for r in rows] == [1, 2]
    assert json.loads(rows[1].values_json)["RPM"]["value"] == 820
