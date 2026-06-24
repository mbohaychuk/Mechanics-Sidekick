import asyncio
import logging

from fastapi import APIRouter, Request

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api", tags=["scanner"])


@router.get("/scanner/status")
async def scanner_status(request: Request) -> dict:
    host = getattr(request.app.state, "obd_host", None)
    if host is None or not host.available:
        return {
            "available": False,
            "scanner_reachable": False,
            "detail": "OBD tool server not running.",
        }
    # async + a short dedicated timeout: the badge polls this constantly, so an unplugged adapter
    # (the slowest get_vehicle_info to fail) must not hold a worker thread for the full OBD timeout
    # or lag the green->amber flip.
    try:
        probe = await asyncio.wait_for(host.call_async("get_vehicle_info", {}), timeout=3.0)
    except Exception:  # noqa: BLE001 — a slow/failed probe just means "not reachable right now"
        logger.debug("scanner status probe failed/timed out", exc_info=True)
        return {"available": True, "scanner_reachable": False,
                "detail": "OBD server up; scanner not reachable."}
    reachable = not probe.lstrip().startswith("[")  # error sentinels start with "["
    detail = "Scanner connected." if reachable else "OBD server up; scanner not reachable."
    return {"available": True, "scanner_reachable": reachable, "detail": detail}
