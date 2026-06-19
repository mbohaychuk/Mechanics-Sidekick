"""Telemetry router tests.

Note on test_live_stream_emits_session_and_samples:
    The Starlette TestClient (starlette 1.3.1 + httpx 0.28.x) uses a fully-buffering
    ASGI transport — portal.call(app, ...) waits for the entire ASGI response before
    returning.  This means client.stream() on an infinite SSE generator blocks forever.
    httpx2 (not yet installed) ships a truly-streaming ASGI transport that would allow
    the brief's exact test pattern.  Until then we exercise the same assertions via a
    direct anyio ASGI invocation that runs server and client concurrently.
"""

import asyncio
import json

import anyio
import pytest
from fastapi.testclient import TestClient

from app.api.main import configure_db, create_app
from app.config import settings
from app.models.vehicle import Vehicle
from app.telemetry.manager import TelemetryManager


class _FakeHost:
    available = True

    async def call_async(self, name, args):
        if name == "get_vehicle_info":
            return json.dumps({"vin": "WAUZZZ"})
        if name == "list_supported_pids":
            return json.dumps([{"pid": "0C", "name": "RPM", "description": "Engine RPM"}])
        if name == "read_live_data":
            return json.dumps([{"name": p, "value": 1, "unit": "x"} for p in args["pids"]])
        return "[obd error] unknown"


def _seed_vehicle(api_client, vin="WAUZZZ"):
    factory = api_client.app.state.session_factory
    s = factory()
    try:
        s.add(Vehicle(year=2004, make="Audi", model="A8", engine="4.2L", vin=vin))
        s.commit()
    finally:
        s.close()


def _install_manager(api_client):
    host = _FakeHost()
    api_client.app.state.obd_host = host
    api_client.app.state.telemetry_manager = TelemetryManager(
        host, api_client.app.state.session_factory, settings
    )


def test_supported_pids(api_client, monkeypatch):
    _seed_vehicle(api_client)
    api_client.app.state.obd_host = _FakeHost()
    r = api_client.get("/api/vehicles/1/supported-pids")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True
    assert "RPM" in body["curated"]
    assert any(p["name"] == "RPM" for p in body["supported"])


@pytest.mark.anyio
async def test_live_stream_emits_session_and_samples(tmp_path):
    """Run server + client concurrently in one event loop to avoid buffering hang.

    httpx 0.28.x ASGITransport and starlette's TestClient both buffer the full
    response before returning.  An infinite SSE generator never finishes, so
    client.stream() hangs.  We work around this by driving the ASGI app directly
    with anyio task groups: the client coroutine signals disconnect after receiving
    enough events, which causes the server's receive() to return http.disconnect and
    allows the generator's finally block to call manager.unsubscribe().
    """
    app = create_app()
    configure_db(app, f"sqlite:///{tmp_path / 'test.db'}")
    host = _FakeHost()
    app.state.obd_host = host
    app.state.telemetry_manager = TelemetryManager(
        host, app.state.session_factory, settings
    )

    # Seed a vehicle directly
    factory = app.state.session_factory
    s = factory()
    try:
        s.add(Vehicle(year=2004, make="Audi", model="A8", engine="4.2L", vin="WAUZZZ"))
        s.commit()
    finally:
        s.close()

    scope = {
        "type": "http",
        "http_version": "1.1",
        "method": "GET",
        "path": "/api/vehicles/1/live",
        "raw_path": b"/api/vehicles/1/live",
        "root_path": "",
        "scheme": "http",
        "query_string": b"pids=RPM%2CSPEED",
        "headers": [],
        "client": ("testclient", 50000),
        "server": ("localhost", 8000),
        "state": {},
        "extensions": {},
    }

    request_complete = False
    response_complete = anyio.Event()
    body_queue: asyncio.Queue = asyncio.Queue()
    events: list[dict] = []

    async def receive():
        nonlocal request_complete
        if not request_complete:
            request_complete = True
            return {"type": "http.request", "body": b""}
        await response_complete.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        await body_queue.put(message)

    async def run_server():
        await app(scope, receive, send)

    async def run_client():
        msg = await body_queue.get()
        assert msg["type"] == "http.response.start"
        assert msg["status"] == 200

        buf = b""
        while True:
            msg = await asyncio.wait_for(body_queue.get(), timeout=5.0)
            if msg["type"] != "http.response.body":
                break
            chunk = msg.get("body", b"")
            buf += chunk
            parts = buf.decode().split("\n\n")
            buf = parts[-1].encode()
            for block in parts[:-1]:
                for line in block.strip().split("\n"):
                    if line.startswith("data:"):
                        events.append(json.loads(line[len("data:"):].strip()))

            if len([e for e in events if e["type"] == "sample"]) >= 2:
                response_complete.set()  # signal server to disconnect
                break

            if not msg.get("more_body", True):
                break

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)
        tg.start_soon(run_client)

    types = [e["type"] for e in events]
    assert types[0] == "session"
    assert "sample" in types
    sample = next(e for e in events if e["type"] == "sample")
    assert set(sample["values"]) == {"RPM", "SPEED"}


def test_live_stream_without_manager_emits_error(api_client):
    _seed_vehicle(api_client)
    api_client.app.state.obd_host = None
    api_client.app.state.telemetry_manager = None
    with api_client.stream("GET", "/api/vehicles/1/live?pids=RPM") as r:
        body = r.read().decode()
    assert '"type": "error"' in body or '"type":"error"' in body
