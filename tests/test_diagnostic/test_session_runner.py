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
    def __init__(self, factory, samples, disconnect_at_end=True):
        self._factory = factory
        self._samples = samples
        self._disconnect_at_end = disconnect_at_end
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
        if self._disconnect_at_end:
            sub.queue.put_nowait({"type": "disconnected", "detail": "scripted end"})
        return live_id, sub, None

    async def unsubscribe(self, sub):
        self.unsubscribed = True


class FakeCommentary:
    def comment(self, window, step, flags, label):
        return Commentary(comment="commentary", adapt=None)


class FakeReportBuilder:
    def __init__(self):
        self.called = False

    def build(self, vehicle_label, good_systems, diagnoses):
        self.called = True
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
    assert "generating" in types  # the report-generation phase is announced...
    assert "report" in types
    assert types.index("generating") < types.index("report")  # ...before the report arrives
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


def test_runner_streams_step_progress_while_holding_a_target():
    # The guided coach needs live per-sample feedback while the operator works toward a step
    # (e.g. holding 2500 rpm), not just a checkmark when it completes.
    factory = _factory()
    s = factory()
    try:
        v = Vehicle(year=2015, make="Ford", model="F-150", engine="5.0L", vin="X")
        s.add(v)
        s.commit()
        vid = v.id
    finally:
        s.close()

    settings = Settings(_env_file=None)
    settings.diag_commentary_interval_s = 999.0  # keep commentary out of this test
    protocol = DiagnosticProtocol(name="t", steps=[
        Step(id="rev_2500", label="Rev", instruction="hold 2500",
             target=StepTarget("RPM", 2300, 2700), capture_pids=["RPM"],
             min_dwell_s=10.0, timeout_s=60.0),  # long dwell so the step stays active
    ])
    samples = [
        {"type": "sample", "seq": 1, "t": 0, "hz": 1.0, "values": {"RPM": {"value": 1500, "unit": "rpm"}}},
        {"type": "sample", "seq": 2, "t": 1000, "hz": 1.0, "values": {"RPM": {"value": 2500, "unit": "rpm"}}},
        {"type": "sample", "seq": 3, "t": 2000, "hz": 1.0, "values": {"RPM": {"value": 2500, "unit": "rpm"}}},
    ]

    def diagnoser_factory(session):
        class _D:
            def diagnose(self, flag, label):
                return Finding(flag.system, flag.severity, flag.detail)
        return _D()

    runner = DiagnosticSessionRunner(
        manager=FakeManager(factory, samples), session_factory=factory, vehicle_id=vid,
        vehicle_label="2015 Ford F-150", protocol=protocol, commentary=FakeCommentary(),
        diagnoser_factory=diagnoser_factory, report_builder=FakeReportBuilder(), settings=settings,
    )

    async def drive():
        return [ev async for ev in runner.run()]

    events = asyncio.run(drive())
    progress = [e for e in events if e["type"] == "step_progress"]
    assert len(progress) == 3
    assert progress[0]["value"] == 1500 and progress[0]["in_range"] is False
    assert progress[1]["value"] == 2500 and progress[1]["in_range"] is True
    assert progress[1]["dwell_elapsed_s"] == 0.0   # just entered the band
    assert progress[2]["dwell_elapsed_s"] == 1.0   # held one more second
    assert progress[2]["dwell_required_s"] == 10.0


def test_runner_ends_on_a_stalled_feed_instead_of_hanging():
    # If live samples stop arriving without a disconnect event (operator walks away, adapter goes
    # quiet), the session must finalize after diag_stall_ticks idle ticks — never hang forever.
    factory = _factory()
    s = factory()
    try:
        v = Vehicle(year=2015, make="Ford", model="F-150", engine="5.0L", vin="X")
        s.add(v)
        s.commit()
        vid = v.id
    finally:
        s.close()

    settings = Settings(_env_file=None)
    settings.diag_commentary_interval_s = 999.0
    settings.diag_stall_ticks = 2  # keep the test fast (~2s of idle ticks)
    protocol = DiagnosticProtocol(name="t", steps=[
        Step(id="idle", label="Idle", instruction="idle", target=StepTarget("RPM", None, 1300),
             capture_pids=["RPM"], min_dwell_s=999.0, timeout_s=999.0),  # never completes
    ])
    samples = [{"type": "sample", "seq": 1, "t": 0, "hz": 1.0, "values": {"RPM": {"value": 600, "unit": "rpm"}}}]

    def diagnoser_factory(session):
        class _D:
            def diagnose(self, flag, label):
                return Finding(flag.system, flag.severity, flag.detail)
        return _D()

    runner = DiagnosticSessionRunner(
        manager=FakeManager(factory, samples, disconnect_at_end=False), session_factory=factory,
        vehicle_id=vid, vehicle_label="2015 Ford F-150", protocol=protocol, commentary=FakeCommentary(),
        diagnoser_factory=diagnoser_factory, report_builder=FakeReportBuilder(), settings=settings,
    )

    async def drive():
        return [ev async for ev in runner.run()]

    events = asyncio.run(drive())
    types = [e["type"] for e in events]
    assert "done" in types  # it finalized rather than hanging
    report = next(e for e in events if e["type"] == "report")
    assert report["overall_status"] == "incomplete"


def test_runner_reports_incomplete_when_no_step_is_completed():
    # If the operator never holds a single guided step (engine off, scanner dropped, etc.), the
    # session must report "incomplete" — not default to a falsely reassuring "good" — and must NOT
    # spend an LLM call interpreting data that doesn't exist.
    factory = _factory()
    s = factory()
    try:
        v = Vehicle(year=2015, make="Ford", model="F-150", engine="5.0L", vin="X")
        s.add(v)
        s.commit()
        vid = v.id
    finally:
        s.close()

    settings = Settings(_env_file=None)
    settings.diag_commentary_interval_s = 999.0
    protocol = DiagnosticProtocol(name="t", steps=[
        Step(id="rev", label="Rev", instruction="hold 2500", target=StepTarget("RPM", 2300, 2700),
             capture_pids=["RPM"], min_dwell_s=10.0, timeout_s=600.0),  # never reached/timed out
    ])
    samples = [  # RPM never enters the band → step stays active → disconnect → no completed step
        {"type": "sample", "seq": 1, "t": 0, "hz": 1.0, "values": {"RPM": {"value": 700, "unit": "rpm"}}},
        {"type": "sample", "seq": 2, "t": 1000, "hz": 1.0, "values": {"RPM": {"value": 720, "unit": "rpm"}}},
    ]

    def diagnoser_factory(session):
        class _D:
            def diagnose(self, flag, label):
                return Finding(flag.system, flag.severity, flag.detail)
        return _D()

    builder = FakeReportBuilder()
    runner = DiagnosticSessionRunner(
        manager=FakeManager(factory, samples), session_factory=factory, vehicle_id=vid,
        vehicle_label="2015 Ford F-150", protocol=protocol, commentary=FakeCommentary(),
        diagnoser_factory=diagnoser_factory, report_builder=builder, settings=settings,
    )

    async def drive():
        return [ev async for ev in runner.run()]

    events = asyncio.run(drive())
    report_ev = next(e for e in events if e["type"] == "report")
    assert report_ev["overall_status"] == "incomplete"
    assert builder.called is False  # no LLM report when there's no completed step to interpret

    sess = factory()
    try:
        row = DiagnosticSessionRepository(sess).list_by_vehicle(vid)[0]
        assert row.overall_status == "incomplete"
        assert row.status == "completed"  # the session ran to the end; the data was just thin
    finally:
        sess.close()
