from fastapi import APIRouter, Request

router = APIRouter(prefix="/api", tags=["scanner"])


@router.get("/scanner/status")
def scanner_status(request: Request) -> dict:
    host = getattr(request.app.state, "obd_host", None)
    if host is None or not host.available:
        return {
            "available": False,
            "scanner_reachable": False,
            "detail": "OBD tool server not running.",
        }
    probe = host.call("get_vehicle_info", {})
    reachable = not probe.lstrip().startswith("[")  # error sentinels start with "["
    detail = "Scanner connected." if reachable else "OBD server up; scanner not reachable."
    return {"available": True, "scanner_reachable": reachable, "detail": detail}
