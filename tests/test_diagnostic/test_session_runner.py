import asyncio
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401
from app.config import Settings
from app.db import Base
from app.diagnostic.commentary import Commentary
from app.diagnostic.protocol import DiagnosticProtocol, Step, StepTarget
from app.diagnostic.report import Finding, HealthReport
from app.diagnostic.session import DiagnosticSessionRunner
from app.models.vehicle import Vehicle
from app.repositories.diagnostic_session_repository import DiagnosticSessionRepository
from app.repositories.live_sample_repository import LiveSampleRepository
from app.repositories.live_session_repository import LiveSessionRepository
from app.telemetry.sampler import Subscriber


def _factory():
    engine = create_engine("sqlite:///:memory:",
                           connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


class FakeManager:
    """Returns a Subscriber pre-loaded with scripted sample events. Records a recorded
    live_session + live_samples so the runner can read capture windows back by seq range."""
    def __init__(self, factory, samples):
        self._factory = factory
        self._samples = samples
        self.unsubscribed = False

    async def subscribe(self, vehicle_id, pids):
        s = self._factory()
        try:
            row = LiveSessionRepository(s).create(vehicle_id, vin=None, target_hz=1.0, pids=pids)
            s.commit()
            live_id = row.id
            LiveSampleRepository(s).bulk_create(
                [{"session_id": live_id, "seq": e["seq"], "t_offset_ms": e["t"], "values": e["values"]}
                 for e in self._samples]
            )
            s.commit()
        finally:
            s.close()
        sub = Subscriber(pids, queue_size=64)
        for e in self._samples:
            sub.queue.put_nowait(e)
        sub.queue.put_nowait({"type": "disconnected", "detail": "scripted end"})
        return live_id, sub, None

    async def unsubscribe(self, sub):
        self.unsubscribed = True


class FakeCommentary:
    def comment(self, window, step, flags, label):
        return Commentary(comment="commentary", adapt=None)


class FakeReportBuilder:
    def build(self, vehicle_label, good_systems, diagnoses):
        findings = [Finding(s, "good", o) for s, o in good_systems.items()] + list(diagnoses)
        return HealthReport(overall_status="fair", summary="done", findings=findings)


def _runner(factory, vid, samples):
    settings = Settings(_env_file=None)
    settings.diag_commentary_interval_s = 0.0  # comment on every tick for the test
    protocol = DiagnosticProtocol(name="t", steps=[
        Step(id="idle_baseline", label="Idle", instruction="idle",
             target=StepTarget("RPM", 550, 1000), capture_pids=["RPM", "LONG_FUEL_TRIM_1"],
             min_dwell_s=0.0, timeout_s=10.0),
    ])

    def diagnoser_factory(session):
        class _D:
            def diagnose(self, flag, label):
                return Finding(flag.system, flag.severity, flag.detail)
        return _D()

    return DiagnosticSessionRunner(
        manager=FakeManager(factory, samples),
        session_factory=factory,
        vehicle_id=vid,
        vehicle_label="2004 Audi A8",
        protocol=protocol,
        commentary=FakeCommentary(),
        diagnoser_factory=diagnoser_factory,
        report_builder=FakeReportBuilder(),
        settings=settings,
    )


def test_runner_emits_full_event_sequence_and_persists_report():
    factory = _factory()
    s = factory()
    try:
        v = Vehicle(year=2004, make="Audi", model="A8", engine="4.2L", vin="X")
        s.add(v)
        s.commit()
        vid = v.id
    finally:
        s.close()

    samples = [
        {"type": "sample", "seq": 1, "t": 0, "hz": 1.0,
         "values": {"RPM": {"value": 700, "unit": "rpm"}, "LONG_FUEL_TRIM_1": {"value": 14.0, "unit": "%"}}},
        {"type": "sample", "seq": 2, "t": 1000, "hz": 1.0,
         "values": {"RPM": {"value": 720, "unit": "rpm"}, "LONG_FUEL_TRIM_1": {"value": 15.0, "unit": "%"}}},
    ]

    runner = _runner(factory, vid, samples)

    async def drive():
        return [ev async for ev in runner.run()]

    events = asyncio.run(drive())
    types = [e["type"] for e in events]
    assert types[0] == "session"
    assert "sample" in types
    assert "step" in types        # idle step completes (dwell 0)
    assert "anomaly" in types     # LTFT +15% lean flagged
    assert "report" in types
    assert types[-1] == "done"
    assert runner._manager.unsubscribed is True  # unsubscribe ran

    report_ev = next(e for e in events if e["type"] == "report")
    assert report_ev["overall_status"] == "fair"

    # persisted, completed, with report_json
    sess = factory()
    try:
        rows = DiagnosticSessionRepository(sess).list_by_vehicle(vid)
        assert len(rows) == 1
        assert rows[0].status == "completed"
        assert json.loads(rows[0].report_json)["summary"] == "done"
        assert rows[0].live_session_id is not None
    finally:
        sess.close()
