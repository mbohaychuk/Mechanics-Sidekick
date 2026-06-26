import asyncio
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.models  # noqa: F401 — register models
from app.config import Settings
from app.db import Base
from app.models.vehicle import Vehicle
from app.repositories.live_session_repository import LiveSessionRepository
from app.repositories.live_sample_repository import LiveSampleRepository
from app.telemetry.manager import LiveSessionConflict, TelemetryManager


class FakeHost:
    """Async OBD host stub: get_vehicle_info returns a VIN; read_live_data echoes values.

    Pass vin_error=True to simulate a VIN read failure (get_vehicle_info returns an OBD
    error sentinel so parse_vin raises LiveReadError). read_live_data still works so the
    sampler can stream samples normally.
    """

    def __init__(self, vin="WAUZZZ", available=True, vin_error=False, dtcs=None, dtc_error=False):
        self.available = available
        self._vin = vin
        self._vin_error = vin_error
        self._dtcs = dtcs or []
        self._dtc_error = dtc_error
        self.dtc_calls: list[dict] = []

    async def call_async(self, name, args):
        if name == "get_vehicle_info":
            if self._vin_error:
                return "[obd error] no link"
            return json.dumps({"vin": self._vin})
        if name == "read_live_data":
            return json.dumps([{"name": p, "value": 1, "unit": "x"} for p in args["pids"]])
        if name == "read_dtcs":
            self.dtc_calls.append(args)
            if self._dtc_error:
                return "[obd unavailable] The OBD tool server is not running."
            return json.dumps({"scope": "all", "count": len(self._dtcs), "codes": self._dtcs})
        return "[obd error] unknown"


def _factory():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


def _seed_vehicle(factory, vin):
    s = factory()
    try:
        v = Vehicle(year=2004, make="Audi", model="A8", engine="4.2L", vin=vin)
        s.add(v)
        s.commit()
        return v.id
    finally:
        s.close()


def test_subscribe_streams_records_and_ends_on_last_unsubscribe():
    factory = _factory()
    vid = _seed_vehicle(factory, "WAUZZZ")
    settings = Settings(_env_file=None)

    async def scenario():
        mgr = TelemetryManager(FakeHost(vin="WAUZZZ"), factory, settings)
        session_id, sub, mismatch = await mgr.subscribe(vid, ["RPM", "SPEED"])
        assert mismatch is None  # VIN matches
        ev = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
        assert ev["type"] == "sample"
        await asyncio.sleep(0.05)  # let a few ticks persist
        await mgr.unsubscribe(sub)
        return session_id

    session_id = asyncio.run(scenario())

    s = factory()
    try:
        row = LiveSessionRepository(s).get_by_id(session_id)
        assert row.status == "ended"
        assert row.ended_utc is not None
        assert row.sample_count >= 1
        assert json.loads(row.pids_json) == ["RPM", "SPEED"]
        assert len(LiveSampleRepository(s).list_by_session(session_id)) >= 1
    finally:
        s.close()


def test_vin_mismatch_is_reported_but_not_blocking():
    factory = _factory()
    vid = _seed_vehicle(factory, "VEHICLE_VIN")
    settings = Settings(_env_file=None)

    async def scenario():
        mgr = TelemetryManager(FakeHost(vin="SCANNER_VIN"), factory, settings)
        _, sub, mismatch = await mgr.subscribe(vid, ["RPM"])
        await mgr.unsubscribe(sub)
        return mismatch

    mismatch = asyncio.run(scenario())
    assert mismatch is not None and "SCANNER_VIN" in mismatch


def test_read_dtcs_parses_codes_and_passes_make():
    factory = _factory()
    settings = Settings(_env_file=None)
    host = FakeHost(dtcs=[
        {"code": "P0706", "scope": "stored", "source": "generic", "description": "TR sensor range"},
        {"code": "P0707", "scope": "stored", "source": "generic", "description": "TR sensor low"},
    ])

    async def scenario():
        mgr = TelemetryManager(host, factory, settings)
        return await mgr.read_dtcs("Ford")

    codes = asyncio.run(scenario())
    assert [c["code"] for c in codes] == ["P0706", "P0707"]
    assert host.dtc_calls and host.dtc_calls[0].get("make") == "Ford"


def test_read_dtcs_returns_none_on_read_failure():
    # A failed read must be None (unavailable), NEVER [] — [] means "checked, no codes".
    factory = _factory()
    settings = Settings(_env_file=None)

    async def scenario():
        mgr = TelemetryManager(FakeHost(dtc_error=True), factory, settings)
        return await mgr.read_dtcs("Ford")

    assert asyncio.run(scenario()) is None


def test_second_vehicle_while_active_conflicts():
    factory = _factory()
    a = _seed_vehicle(factory, "A")
    b = _seed_vehicle(factory, "B")
    settings = Settings(_env_file=None)

    async def scenario():
        mgr = TelemetryManager(FakeHost(vin="A"), factory, settings)
        _, sub_a, _ = await mgr.subscribe(a, ["RPM"])
        try:
            await mgr.subscribe(b, ["RPM"])
            return "no-conflict"
        except LiveSessionConflict as exc:
            return exc.active_vehicle_id
        finally:
            await mgr.unsubscribe(sub_a)

    assert asyncio.run(scenario()) == a


def test_vin_read_error_does_not_block_session():
    """A VIN-check read failure (LiveReadError) must not prevent subscribe from succeeding.
    mismatch must be None and the session must stream samples and close cleanly."""
    factory = _factory()
    vid = _seed_vehicle(factory, "WAUZZZ")
    settings = Settings(_env_file=None)

    async def scenario():
        mgr = TelemetryManager(FakeHost(vin_error=True), factory, settings)
        session_id, sub, mismatch = await mgr.subscribe(vid, ["RPM"])
        assert mismatch is None  # read failure → no mismatch detail
        ev = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
        assert ev["type"] == "sample"
        await asyncio.sleep(0.05)  # let a few ticks persist before drain
        await mgr.unsubscribe(sub)
        return session_id

    session_id = asyncio.run(scenario())

    s = factory()
    try:
        row = LiveSessionRepository(s).get_by_id(session_id)
        assert row.status == "ended"
        assert row.sample_count >= 1
    finally:
        s.close()
