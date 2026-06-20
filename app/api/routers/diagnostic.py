import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.config import settings
from app.repositories.diagnostic_session_repository import DiagnosticSessionRepository
from app.services.factories import make_diagnostic_runner

router = APIRouter(prefix="/api", tags=["diagnostic"])


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


def _error_stream(detail: str):
    async def gen():
        yield _sse({"type": "error", "detail": detail})
        yield _sse({"type": "done"})
    return StreamingResponse(gen(), media_type="text/event-stream")


@router.post("/vehicles/{vehicle_id}/diagnostic")
async def start_diagnostic(vehicle_id: int, request: Request, protocol: str = "default"):
    manager = getattr(request.app.state, "telemetry_manager", None)
    host = getattr(request.app.state, "obd_host", None)
    session_factory = request.app.state.session_factory

    if manager is None or host is None or not host.available:
        return _error_stream("OBD tool server not running.")

    if manager.active_vehicle_id is not None and manager.active_vehicle_id != vehicle_id:
        raise HTTPException(
            status_code=409,
            detail=f"A live session is already active for vehicle {manager.active_vehicle_id}.",
        )

    runner = make_diagnostic_runner(session_factory, settings, manager, host, vehicle_id, protocol)
    if runner is None:
        return _error_stream("Vehicle not found or diagnostics unavailable.")

    async def stream():
        async for event in runner.run():
            yield _sse(event)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/vehicles/{vehicle_id}/diagnostic-reports")
def list_reports(vehicle_id: int, session: Session = Depends(get_session)) -> list[dict]:
    rows = DiagnosticSessionRepository(session).list_by_vehicle(
        vehicle_id, limit=settings.diag_report_recent_limit
    )
    return [
        {
            "id": r.id,
            "status": r.status,
            "protocol_name": r.protocol_name,
            "started_utc": r.started_utc.isoformat(),
            "ended_utc": r.ended_utc.isoformat() if r.ended_utc else None,
            "overall_status": r.overall_status,
            "summary": r.summary,
        }
        for r in rows
    ]


@router.get("/diagnostic-sessions/{session_id}")
def get_report(session_id: int, session: Session = Depends(get_session)) -> dict:
    row = DiagnosticSessionRepository(session).get_by_id(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Diagnostic session {session_id} not found")
    report = None
    if row.report_json:
        try:
            report = json.loads(row.report_json)
        except (ValueError, TypeError):
            report = None  # one corrupt row must not 500 the endpoint
    return {
        "session": {
            "id": row.id, "vehicle_id": row.vehicle_id, "status": row.status,
            "protocol_name": row.protocol_name, "overall_status": row.overall_status,
            "started_utc": row.started_utc.isoformat(),
            "ended_utc": row.ended_utc.isoformat() if row.ended_utc else None,
        },
        "report": report,
    }
