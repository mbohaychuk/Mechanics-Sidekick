import asyncio
import json
from unittest.mock import MagicMock

import anyio
import pytest

from app.api.main import configure_db, create_app
from app.config import settings
from app.models.vehicle import Vehicle
from app.repositories.diagnostic_session_repository import DiagnosticSessionRepository
from app.telemetry.manager import TelemetryManager


class _FakeHost:
    available = True

    async def call_async(self, name, args):
        if name == "get_vehicle_info":
            return json.dumps({"vin": "WAUZZZ"})
        if name == "read_live_data":
            # idle RPM in [550,1000] so the idle step completes; lean LTFT to force an anomaly
            return json.dumps([
                {"name": p, "value": (700 if p == "RPM" else (14 if "FUEL_TRIM" in p else 88)), "unit": "x"}
                for p in args["pids"]
            ])
        return "[obd error] unknown"


class _FakeProvider:
    """Stands in for OpenAIProvider so the endpoint needs no API key. Returns valid JSON."""
    def stream_turn(self, messages, tools, max_tokens=None):
        from app.agent.provider import ProviderTurn
        is_report = any("health report" in m.get("content", "") for m in messages)
        raw = (json.dumps({"summary": "ok", "findings": {}}) if is_report
               else json.dumps({"comment": "looks fine", "adapt": None}))
        yield {"type": "turn", "turn": ProviderTurn(text=raw, tool_calls=[])}


def _seed_vehicle(app):
    f = app.state.session_factory
    s = f()
    try:
        s.add(Vehicle(year=2004, make="Audi", model="A8", engine="4.2L", vin="WAUZZZ"))
        s.commit()
    finally:
        s.close()


@pytest.mark.anyio
async def test_diagnostic_stream_runs_and_persists(tmp_path, monkeypatch):
    app = create_app()
    configure_db(app, f"sqlite:///{tmp_path / 'd.db'}")
    host = _FakeHost()
    app.state.obd_host = host
    app.state.telemetry_manager = TelemetryManager(host, app.state.session_factory, settings)
    _seed_vehicle(app)

    # Force the runner to use the fake provider + a fake embedding backend (no OpenAI key in
    # tests) — same pattern as tests/test_api/test_chat.py.
    import app.services.factories as factories
    monkeypatch.setattr(factories, "OpenAIProvider", lambda **kw: _FakeProvider())
    _fake_embedding = MagicMock()
    _fake_embedding.embed_query.return_value = [0.0, 1.0]
    monkeypatch.setattr(factories, "make_embedding_service", lambda s: _fake_embedding)

    # Use a fast single-step protocol so the test completes in seconds against the real ~1 Hz
    # sampler (the real DEFAULT_PROTOCOL has 15 s dwells / 45 s timeouts).
    from app.diagnostic.protocol import DiagnosticProtocol, Step, StepTarget
    fast = DiagnosticProtocol(name="default", steps=[
        Step(id="idle_baseline", label="Idle", instruction="idle",
             target=StepTarget("RPM", 550, 1000), capture_pids=["RPM", "LONG_FUEL_TRIM_1"],
             min_dwell_s=0.0, timeout_s=5.0),
    ])
    monkeypatch.setattr(factories, "get_protocol", lambda name: fast)

    scope = {
        "type": "http", "http_version": "1.1", "method": "POST",
        "path": "/api/vehicles/1/diagnostic", "raw_path": b"/api/vehicles/1/diagnostic",
        "root_path": "", "scheme": "http", "query_string": b"protocol=default",
        "headers": [(b"content-type", b"application/json")],
        "client": ("testclient", 50000), "server": ("localhost", 8000),
        "state": {}, "extensions": {},
    }
    request_complete = False
    response_complete = anyio.Event()
    body_queue: asyncio.Queue = asyncio.Queue()
    events: list[dict] = []

    async def receive():
        nonlocal request_complete
        if not request_complete:
            request_complete = True
            return {"type": "http.request", "body": b"{}"}
        await response_complete.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        await body_queue.put(message)

    async def run_server():
        await app(scope, receive, send)

    async def run_client():
        msg = await body_queue.get()
        assert msg["type"] == "http.response.start" and msg["status"] == 200
        buf = b""
        while True:
            msg = await asyncio.wait_for(body_queue.get(), timeout=10.0)
            if msg["type"] != "http.response.body":
                break
            buf += msg.get("body", b"")
            parts = buf.decode().split("\n\n")
            buf = parts[-1].encode()
            for block in parts[:-1]:
                for line in block.strip().split("\n"):
                    if line.startswith("data:"):
                        events.append(json.loads(line[len("data:"):].strip()))
            if any(e["type"] == "done" for e in events):
                response_complete.set()
                break

    async with anyio.create_task_group() as tg:
        tg.start_soon(run_server)
        tg.start_soon(run_client)

    types = [e["type"] for e in events]
    assert types[0] == "session"
    assert "report" in types and types[-1] == "done"

    f = app.state.session_factory
    s = f()
    try:
        rows = DiagnosticSessionRepository(s).list_by_vehicle(1)
        assert rows and rows[0].status == "completed"
    finally:
        s.close()


def test_diagnostic_reports_list_and_detail(tmp_path):
    from fastapi.testclient import TestClient
    app = create_app()
    configure_db(app, f"sqlite:///{tmp_path / 'd2.db'}")
    _seed_vehicle(app)
    # Seed a completed diagnostic session directly.
    f = app.state.session_factory
    s = f()
    try:
        repo = DiagnosticSessionRepository(s)
        row = repo.create(vehicle_id=1, live_session_id=None, protocol_name="default")
        s.commit()
        repo.complete(row.id, overall_status="fair", summary="ok",
                      report_json=json.dumps({"overall_status": "fair", "summary": "ok", "findings": []}),
                      commentary_json="[]")
        s.commit()
        sid = row.id
    finally:
        s.close()

    with TestClient(app) as client:
        lst = client.get("/api/vehicles/1/diagnostic-reports")
        assert lst.status_code == 200
        assert lst.json()[0]["overall_status"] == "fair"
        detail = client.get(f"/api/diagnostic-sessions/{sid}")
        assert detail.status_code == 200
        assert detail.json()["report"]["summary"] == "ok"
        assert client.get("/api/diagnostic-sessions/9999").status_code == 404
