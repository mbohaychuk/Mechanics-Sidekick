import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.config import settings
from app.telemetry.manager import LiveSessionConflict
from app.telemetry.parse import LiveReadError, parse_supported_pids
from app.telemetry.pids import CURATED_PIDS
from app.repositories.live_sample_repository import LiveSampleRepository
from app.repositories.live_session_repository import LiveSessionRepository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["telemetry"])


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event)}\n\n"


@router.get("/vehicles/{vehicle_id}/supported-pids")
async def supported_pids(vehicle_id: int, request: Request) -> dict:
    host = getattr(request.app.state, "obd_host", None)
    if host is None or not host.available:
        return {"available": False, "curated": CURATED_PIDS, "supported": []}
    try:
        supported = parse_supported_pids(await host.call_async("list_supported_pids", {}))
    except LiveReadError as exc:
        logger.warning("list_supported_pids failed for vehicle %s; returning curated PIDs only: %s",
                       vehicle_id, str(exc)[:200])
        supported = []
    return {"available": True, "curated": CURATED_PIDS, "supported": supported}


@router.get("/vehicles/{vehicle_id}/live")
async def live(vehicle_id: int, pids: str, request: Request):
    manager = getattr(request.app.state, "telemetry_manager", None)
    host = getattr(request.app.state, "obd_host", None)
    pid_list = [p.strip() for p in pids.split(",") if p.strip()][: settings.live_max_pids]

    if manager is None or host is None or not host.available:
        async def err():
            yield _sse({"type": "error", "detail": "OBD tool server not running."})
            yield _sse({"type": "done"})

        return StreamingResponse(err(), media_type="text/event-stream")

    # Fast 409 for the common conflict (a session already active for another vehicle).
    if manager.active_vehicle_id is not None and manager.active_vehicle_id != vehicle_id:
        raise HTTPException(
            status_code=409,
            detail=f"A live session is already active for vehicle {manager.active_vehicle_id}.",
        )

    async def stream():
        sub = None
        try:
            session_id, sub, mismatch = await manager.subscribe(vehicle_id, pid_list)
            yield _sse({"type": "session", "session_id": session_id, "target_hz": manager.target_hz})
            if mismatch:
                yield _sse({"type": "vin_mismatch", "detail": mismatch})
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                yield _sse(event)
                if event["type"] in ("disconnected", "error"):
                    break
        except LiveSessionConflict as exc:
            # Rare TOCTOU: another vehicle's session started between the pre-check and subscribe.
            yield _sse({
                "type": "error",
                "detail": f"A live session is already active for vehicle {exc.active_vehicle_id}.",
            })
        except Exception:  # noqa: BLE001 — any other subscribe/stream failure must surface, not hang
            logger.exception("Live telemetry stream failed for vehicle %s", vehicle_id)
            yield _sse({"type": "error", "detail": "Live telemetry failed to start."})
            yield _sse({"type": "done"})
        finally:
            if sub is not None:
                await manager.unsubscribe(sub)

    return StreamingResponse(stream(), media_type="text/event-stream")


@router.get("/vehicles/{vehicle_id}/sessions")
def list_sessions(vehicle_id: int, session: Session = Depends(get_session)) -> list[dict]:
    rows = LiveSessionRepository(session).list_by_vehicle(vehicle_id)
    return [
        {
            "id": r.id,
            "vehicle_id": r.vehicle_id,
            "status": r.status,
            "started_utc": r.started_utc.isoformat(),
            "ended_utc": r.ended_utc.isoformat() if r.ended_utc else None,
            "achieved_hz": r.achieved_hz,
            "sample_count": r.sample_count,
            "pids": json.loads(r.pids_json),
        }
        for r in rows
    ]


@router.get("/sessions/{session_id}")
def get_session_series(session_id: int, session: Session = Depends(get_session)) -> dict:
    row = LiveSessionRepository(session).get_by_id(session_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"Session {session_id} not found")
    samples = LiveSampleRepository(session).list_by_session(session_id)
    return {
        "session": {
            "id": row.id,
            "vehicle_id": row.vehicle_id,
            "status": row.status,
            "pids": json.loads(row.pids_json),
            "sample_count": row.sample_count,
        },
        "samples": [
            {"seq": s.seq, "t": s.t_offset_ms, "values": json.loads(s.values_json)} for s in samples
        ],
    }
