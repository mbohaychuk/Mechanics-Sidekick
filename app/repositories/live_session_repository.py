import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.live_session import LiveSession


class LiveSessionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self, vehicle_id: int, vin: str | None, target_hz: float, pids: list[str]
    ) -> LiveSession:
        row = LiveSession(
            vehicle_id=vehicle_id,
            vin=vin,
            target_hz=target_hz,
            pids_json=json.dumps(pids),
        )
        self.session.add(row)
        return row

    def mark_ended(
        self, session_id: int, status: str, achieved_hz: float | None, sample_count: int
    ) -> None:
        row = self.session.get(LiveSession, session_id)
        if row is None:
            return
        row.status = status
        row.achieved_hz = achieved_hz
        row.sample_count = sample_count
        row.ended_utc = datetime.now(timezone.utc)

    def get_by_id(self, session_id: int) -> LiveSession | None:
        return self.session.get(LiveSession, session_id)

    def list_by_vehicle(self, vehicle_id: int) -> list[LiveSession]:
        return (
            self.session.query(LiveSession)
            .filter(LiveSession.vehicle_id == vehicle_id)
            .order_by(LiveSession.id.desc())
            .all()
        )

    def latest_pids(self, vehicle_id: int) -> list[str] | None:
        rows = self.list_by_vehicle(vehicle_id)
        if not rows:
            return None
        return json.loads(rows[0].pids_json)
