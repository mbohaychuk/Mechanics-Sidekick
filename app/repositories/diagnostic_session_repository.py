from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.diagnostic_session import DiagnosticSession


class DiagnosticSessionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self, vehicle_id: int, live_session_id: int | None, protocol_name: str
    ) -> DiagnosticSession:
        row = DiagnosticSession(
            vehicle_id=vehicle_id,
            live_session_id=live_session_id,
            protocol_name=protocol_name,
        )
        self.session.add(row)
        return row

    def complete(
        self,
        session_id: int,
        overall_status: str,
        summary: str,
        report_json: str,
        commentary_json: str,
    ) -> None:
        row = self.session.get(DiagnosticSession, session_id)
        if row is None:
            return
        row.status = "completed"
        row.overall_status = overall_status
        row.summary = summary
        row.report_json = report_json
        row.commentary_json = commentary_json
        row.ended_utc = datetime.now(timezone.utc)

    def mark_error(self, session_id: int) -> None:
        row = self.session.get(DiagnosticSession, session_id)
        if row is None:
            return
        row.status = "error"
        row.ended_utc = datetime.now(timezone.utc)

    def get_by_id(self, session_id: int) -> DiagnosticSession | None:
        return self.session.get(DiagnosticSession, session_id)

    def list_by_vehicle(self, vehicle_id: int, limit: int | None = None) -> list[DiagnosticSession]:
        q = (
            self.session.query(DiagnosticSession)
            .filter(DiagnosticSession.vehicle_id == vehicle_id)
            .order_by(DiagnosticSession.id.desc())
        )
        if limit is not None:
            q = q.limit(limit)
        return q.all()
