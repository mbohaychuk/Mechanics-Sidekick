import json

from sqlalchemy.orm import Session

from app.models.live_sample import LiveSample


class LiveSampleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def bulk_create(self, rows: list[dict]) -> None:
        self.session.add_all(
            LiveSample(
                session_id=r["session_id"],
                seq=r["seq"],
                t_offset_ms=r["t_offset_ms"],
                values_json=json.dumps(r["values"]),
            )
            for r in rows
        )

    def list_by_session(self, session_id: int) -> list[LiveSample]:
        return (
            self.session.query(LiveSample)
            .filter(LiveSample.session_id == session_id)
            .order_by(LiveSample.seq)
            .all()
        )
