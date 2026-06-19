# Live Telemetry Dashboard — Backend (Plan A) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the backend for the live telemetry dashboard — a per-vehicle SSE stream of live OBD PIDs, driven by one shared per-adapter async sampler over the existing `obd-mcp` connection, recording each session to SQLite off the hot path.

**Architecture:** `ObdMcpHost` gains an `asyncio.Lock` (serializes all adapter access) and an async `call_async`. A `TelemetrySampler` runs one async poll loop per adapter, reading the union of subscribed PIDs via `read_live_data`, fanning samples out to per-subscriber latest-wins queues, and enqueuing them to a batched `Recorder` (off the sampling loop). A `TelemetryManager` enforces one active session at a time and owns the session-row lifecycle. An async SSE endpoint subscribes browsers to the sampler.

**Tech Stack:** Python 3.11+, FastAPI (async `StreamingResponse`/SSE), asyncio, the MCP Python SDK (existing), SQLAlchemy 2.0 (existing), pytest. **No new runtime dependency.**

This is **Plan A (backend)** of the live telemetry dashboard. The Vue Live view is **Plan B** (a separate plan, after this ships). It produces working, curl-testable software: a live telemetry API with recording.

## Global Constraints

- Python ≥ 3.11; deps via `uv`; run via `uv run`. **No new dependency** (no `pytest-asyncio`, no `aiosqlite`).
- The concurrency model is fixed by physics (per the design spec): one ELM327 → one `obd-mcp` process → one MCP session → **one serializing lock** → **one shared sampler** → N subscribers. Do not add a second connection or a per-client poll loop.
- All OBD access serializes through `ObdMcpHost`'s lock. The live path uses the new **async** `call_async`; the existing chat path keeps the sync `call`. Both funnel through `_call_async` (one lock).
- Live sampling drives **our own poll loop calling `read_live_data` once per tick** — never `obd-mcp`'s `record_session` (a batch tool that would trip the 30 s call timeout).
- The live SSE endpoint is **`async def`** + an async generator (never a sync generator in the threadpool). Recording happens **off** the sampling loop via a batched writer using a fresh sync `Session` in a thread executor.
- `read_live_data` returns a JSON **array** `[{pid,name,value,unit,timestamp}|{pid,name,error,timestamp}]`. A successful result starts with `[`, the same prefix as host error sentinels (`[obd error]`, `[tool error]`, `[obd unavailable]`) — so distinguish results from sentinels with `json.loads` success/failure, **never a prefix check**.
- Async logic is tested by driving coroutines with `asyncio.run(...)` inside ordinary sync `pytest` functions (no `pytest-asyncio`). The OBD host is always a fake/stub in tests — no real `obd-mcp`, no scanner, no network.
- Run the full suite with `uv run pytest tests/ -v`; the existing CLI + all prior tests stay green. Schema additions use `Base.metadata.create_all` (no Alembic). Commit messages plain, conventional-commit; no AI attribution.

---

### Task 1: Config additions + curated PID set

**Files:**
- Modify: `app/config.py`
- Create: `app/telemetry/__init__.py` (empty), `app/telemetry/pids.py`
- Modify: `.env.example`
- Test: `tests/test_telemetry/__init__.py` (empty), `tests/test_telemetry/test_config_pids.py` (create)

**Interfaces:**
- Produces: `Settings` fields `live_sample_hz: float`, `live_min_interval_s: float`, `live_max_pids: int`, `live_subscriber_queue: int`, `live_recorder_batch: int`; and `app.telemetry.pids.CURATED_PIDS: list[str]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_telemetry/__init__.py` (empty). Create `tests/test_telemetry/test_config_pids.py`:
```python
from app.config import Settings
from app.telemetry.pids import CURATED_PIDS


def test_live_settings_defaults():
    s = Settings(_env_file=None)
    assert s.live_sample_hz == 1.0
    assert s.live_min_interval_s == 0.25
    assert s.live_max_pids == 16
    assert s.live_subscriber_queue == 2
    assert s.live_recorder_batch == 20


def test_curated_pids_are_canonical_names():
    assert "RPM" in CURATED_PIDS
    assert "SPEED" in CURATED_PIDS
    assert "COOLANT_TEMP" in CURATED_PIDS
    # all entries are non-empty upper-case python-OBD command names
    assert all(p == p.upper() and p for p in CURATED_PIDS)
    assert len(CURATED_PIDS) == len(set(CURATED_PIDS))  # no dupes
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_telemetry/test_config_pids.py -v`
Expected: FAIL — `ModuleNotFoundError: app.telemetry.pids` / missing fields.

- [ ] **Step 3: Add the config fields**

In `app/config.py`, add after `web_search_max_results` (before `model_config`):
```python
    live_sample_hz: float = 1.0
    live_min_interval_s: float = 0.25
    live_max_pids: int = 16
    live_subscriber_queue: int = 2
    live_recorder_batch: int = 20
```

- [ ] **Step 4: Add the curated PID list**

Create `app/telemetry/__init__.py` (empty). Create `app/telemetry/pids.py`:
```python
# Canonical python-OBD Mode 01 command names. The dashboard offers these by
# default, filtered at runtime against the ECU's supported set.
CURATED_PIDS: list[str] = [
    "RPM",
    "SPEED",
    "COOLANT_TEMP",
    "INTAKE_TEMP",
    "MAF",
    "THROTTLE_POS",
    "ENGINE_LOAD",
    "TIMING_ADVANCE",
    "SHORT_FUEL_TRIM_1",
    "LONG_FUEL_TRIM_1",
    "O2_B1S1",
    "O2_B1S2",
]
```

- [ ] **Step 5: Document the env vars**

Append to `.env.example`:
```bash
# Live telemetry dashboard
LIVE_SAMPLE_HZ=1.0
LIVE_MIN_INTERVAL_S=0.25
LIVE_MAX_PIDS=16
```

- [ ] **Step 6: Run the test + full suite, commit**

Run: `uv run pytest tests/test_telemetry/test_config_pids.py -v` → PASS.
Run: `uv run pytest tests/ -v` → PASS.
```bash
git add app/config.py app/telemetry/__init__.py app/telemetry/pids.py .env.example tests/test_telemetry
git commit -m "feat(telemetry): live config settings and curated PID set"
```

---

### Task 2: `live_session` / `live_sample` models + repositories

**Files:**
- Create: `app/models/live_session.py`, `app/models/live_sample.py`
- Modify: `app/models/__init__.py`
- Create: `app/repositories/live_session_repository.py`, `app/repositories/live_sample_repository.py`
- Test: `tests/test_repositories/test_live_repos.py` (create)

**Interfaces:**
- Produces:
  - `LiveSession(id, vehicle_id, vin, started_utc, ended_utc, status, target_hz, achieved_hz, pids_json, sample_count)`; `LiveSample(id, session_id, seq, recorded_utc, t_offset_ms, values_json)`.
  - `LiveSessionRepository(session)`: `create(vehicle_id, vin, target_hz, pids) -> LiveSession`, `mark_ended(session_id, status, achieved_hz, sample_count) -> None`, `get_by_id(id) -> LiveSession | None`, `list_by_vehicle(vehicle_id) -> list[LiveSession]`, `latest_pids(vehicle_id) -> list[str] | None`.
  - `LiveSampleRepository(session)`: `bulk_create(rows: list[dict]) -> None` (each `{session_id, seq, t_offset_ms, values}`), `list_by_session(session_id) -> list[LiveSample]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_repositories/test_live_repos.py`:
```python
import json

from app.models.vehicle import Vehicle
from app.repositories.live_session_repository import LiveSessionRepository
from app.repositories.live_sample_repository import LiveSampleRepository


def _vehicle(db_session, vin="WAUZZZ"):
    v = Vehicle(year=2004, make="Audi", model="A8", engine="4.2L", vin=vin)
    db_session.add(v)
    db_session.flush()
    return v.id


def test_session_create_end_and_latest_pids(db_session):
    vid = _vehicle(db_session)
    repo = LiveSessionRepository(db_session)

    s = repo.create(vehicle_id=vid, vin="WAUZZZ", target_hz=1.0, pids=["RPM", "SPEED"])
    db_session.flush()
    assert s.id is not None
    assert s.status == "recording"
    assert json.loads(s.pids_json) == ["RPM", "SPEED"]

    repo.mark_ended(s.id, status="ended", achieved_hz=0.8, sample_count=12)
    again = repo.get_by_id(s.id)
    assert again.status == "ended"
    assert again.ended_utc is not None
    assert again.achieved_hz == 0.8
    assert again.sample_count == 12

    assert repo.latest_pids(vid) == ["RPM", "SPEED"]
    assert [x.id for x in repo.list_by_vehicle(vid)] == [s.id]


def test_sample_bulk_create_and_list(db_session):
    vid = _vehicle(db_session)
    s = LiveSessionRepository(db_session).create(vehicle_id=vid, vin=None, target_hz=1.0, pids=["RPM"])
    db_session.flush()

    samples = LiveSampleRepository(db_session)
    samples.bulk_create([
        {"session_id": s.id, "seq": 1, "t_offset_ms": 0, "values": {"RPM": {"value": 800, "unit": "rpm"}}},
        {"session_id": s.id, "seq": 2, "t_offset_ms": 1000, "values": {"RPM": {"value": 820, "unit": "rpm"}}},
    ])
    db_session.flush()

    rows = samples.list_by_session(s.id)
    assert [r.seq for r in rows] == [1, 2]
    assert json.loads(rows[1].values_json)["RPM"]["value"] == 820
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_repositories/test_live_repos.py -v`
Expected: FAIL — model/repo modules missing.

- [ ] **Step 3: Create the models**

Create `app/models/live_session.py`:
```python
from datetime import datetime, timezone

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LiveSession(Base):
    __tablename__ = "live_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    vin: Mapped[str | None] = mapped_column(String(32), default=None)
    started_utc: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    ended_utc: Mapped[datetime | None] = mapped_column(default=None)
    status: Mapped[str] = mapped_column(String(20), default="recording")
    target_hz: Mapped[float] = mapped_column(default=1.0)
    achieved_hz: Mapped[float | None] = mapped_column(default=None)
    pids_json: Mapped[str] = mapped_column(default="[]")
    sample_count: Mapped[int] = mapped_column(default=0)
```

Create `app/models/live_sample.py`:
```python
from datetime import datetime, timezone

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class LiveSample(Base):
    __tablename__ = "live_samples"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("live_sessions.id"))
    seq: Mapped[int] = mapped_column()
    recorded_utc: Mapped[datetime] = mapped_column(default=lambda: datetime.now(timezone.utc))
    t_offset_ms: Mapped[int] = mapped_column(default=0)
    values_json: Mapped[str] = mapped_column(default="{}")
```

- [ ] **Step 4: Register the models**

Replace `app/models/__init__.py`:
```python
# app/models/__init__.py
from app.models.vehicle import Vehicle
from app.models.document import Document
from app.models.document_chunk import DocumentChunk
from app.models.job import Job
from app.models.chat_message import ChatMessage
from app.models.live_session import LiveSession
from app.models.live_sample import LiveSample

__all__ = [
    "Vehicle",
    "Document",
    "DocumentChunk",
    "Job",
    "ChatMessage",
    "LiveSession",
    "LiveSample",
]
```

- [ ] **Step 5: Create the repositories**

Create `app/repositories/live_session_repository.py`:
```python
import json
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models.live_session import LiveSession


class LiveSessionRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def create(
        self, vehicle_id: int, vin: str | None, target_hz: float, pids: list[str]
    ) -> LiveSession:
        row = LiveSession(
            vehicle_id=vehicle_id,
            vin=vin,
            target_hz=target_hz,
            pids_json=json.dumps(pids),
        )
        self.session.add(row)
        return row

    def mark_ended(
        self, session_id: int, status: str, achieved_hz: float | None, sample_count: int
    ) -> None:
        row = self.session.get(LiveSession, session_id)
        if row is None:
            return
        row.status = status
        row.achieved_hz = achieved_hz
        row.sample_count = sample_count
        row.ended_utc = datetime.now(timezone.utc)

    def get_by_id(self, session_id: int) -> LiveSession | None:
        return self.session.get(LiveSession, session_id)

    def list_by_vehicle(self, vehicle_id: int) -> list[LiveSession]:
        return (
            self.session.query(LiveSession)
            .filter(LiveSession.vehicle_id == vehicle_id)
            .order_by(LiveSession.id.desc())
            .all()
        )

    def latest_pids(self, vehicle_id: int) -> list[str] | None:
        rows = self.list_by_vehicle(vehicle_id)
        if not rows:
            return None
        return json.loads(rows[0].pids_json)
```

Create `app/repositories/live_sample_repository.py`:
```python
import json

from sqlalchemy.orm import Session

from app.models.live_sample import LiveSample


class LiveSampleRepository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def bulk_create(self, rows: list[dict]) -> None:
        self.session.add_all(
            LiveSample(
                session_id=r["session_id"],
                seq=r["seq"],
                t_offset_ms=r["t_offset_ms"],
                values_json=json.dumps(r["values"]),
            )
            for r in rows
        )

    def list_by_session(self, session_id: int) -> list[LiveSample]:
        return (
            self.session.query(LiveSample)
            .filter(LiveSample.session_id == session_id)
            .order_by(LiveSample.seq)
            .all()
        )
```

- [ ] **Step 6: Run the test + full suite, commit**

Run: `uv run pytest tests/test_repositories/test_live_repos.py -v` → PASS.
Run: `uv run pytest tests/ -v` → PASS.
```bash
git add app/models tests/test_repositories/test_live_repos.py app/repositories/live_session_repository.py app/repositories/live_sample_repository.py
git commit -m "feat(telemetry): live_session/live_sample models and repositories"
```

---

### Task 3: `ObdMcpHost` serialization lock + async `call_async`

**Files:**
- Modify: `app/agent/mcp_host.py`
- Test: `tests/test_agent/test_mcp_host.py` (extend — it already has the stub-server integration tests)

**Interfaces:**
- Consumes: the existing `ObdMcpHost`, the in-repo `tests/fixtures/stub_mcp_server.py`.
- Produces: `ObdMcpHost.call_async(name: str, args: dict) -> str` (an `async` method awaitable from any event loop); all `call_tool` invocations serialize through a per-host `asyncio.Lock`. The existing sync `call()` is unchanged in behavior.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_agent/test_mcp_host.py`:
```python
import asyncio  # noqa: E402  (grouped with the new tests for clarity)


def test_call_async_returns_result_against_stub():
    host = ObdMcpHost(command=sys.executable, args=[STUB], start_timeout=20.0)
    assert host.start() is True
    try:
        out = asyncio.run(host.call_async("echo", {"text": "live"}))
        assert "echo:live" in out
    finally:
        host.stop()


def test_call_async_serializes_concurrent_calls():
    host = ObdMcpHost(command=sys.executable, args=[STUB], start_timeout=20.0)
    assert host.start() is True
    try:
        async def hammer():
            return await asyncio.gather(*[host.call_async("echo", {"text": str(i)}) for i in range(5)])

        results = asyncio.run(hammer())
        # all five complete and return their own value — no interleaved/garbled frames
        assert sorted(r.split("echo:")[1] for r in results) == ["0", "1", "2", "3", "4"]
    finally:
        host.stop()


def test_call_async_degrades_when_unavailable():
    host = ObdMcpHost(command="/nonexistent-binary-xyz", args=[], start_timeout=5.0)
    try:
        assert host.start() is False
        out = asyncio.run(host.call_async("echo", {"text": "x"}))
        assert out.startswith("[obd unavailable]")
    finally:
        host.stop()
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_agent/test_mcp_host.py -k call_async -v`
Expected: FAIL — `AttributeError: 'ObdMcpHost' object has no attribute 'call_async'`.

- [ ] **Step 3: Add the lock and `call_async`**

In `app/agent/mcp_host.py`:

(a) In `__init__`, add after `self._start_error = ...`:
```python
        self._lock: asyncio.Lock | None = None
```

(b) In `_connect`, create the lock on the host loop — add as the first line inside the `try:`:
```python
            self._lock = asyncio.Lock()
```
(so the full start of `_connect` reads:)
```python
    async def _connect(self) -> None:
        try:
            self._lock = asyncio.Lock()
            self._stack = AsyncExitStack()
```

(c) Replace `_call_async` to acquire the lock:
```python
    async def _call_async(self, name: str, args: dict) -> str:
        assert self._lock is not None
        async with self._lock:
            result = await self._session.call_tool(name, args)
        return result_to_text(result)
```

(d) Add the public async method after `_call_async`:
```python
    async def call_async(self, name: str, args: dict) -> str:
        if not self.available:
            return "[obd unavailable] The OBD tool server is not running."
        if name not in self._allowed:
            return f"[obd error] Tool '{name}' is not available."
        if self._loop is None or self._loop.is_closed():
            return "[obd unavailable] The OBD tool server is not running."
        future = asyncio.run_coroutine_threadsafe(self._call_async(name, args), self._loop)
        try:
            return await asyncio.wait_for(asyncio.wrap_future(future), self._call_timeout)
        except Exception as exc:
            logger.exception("OBD tool %s failed (async)", name)
            return f"[tool error] {name}: {exc}"
```
(The lock lives on and is awaited only from the host's private loop — both the sync `call()` path and `call_async()` submit `_call_async` to that loop via `run_coroutine_threadsafe`, so every `call_tool` serializes through the one lock. `call_async` is awaitable from a *different* loop because `asyncio.wrap_future` adapts the cross-thread `concurrent.futures.Future` to the caller's loop.)

- [ ] **Step 4: Run the host tests + full suite**

Run: `uv run pytest tests/test_agent/test_mcp_host.py -v`
Expected: PASS — the three new `call_async` tests plus the existing host tests (the lock is uncontended on the sequential `call()` path, so existing behavior is unchanged).
Run: `uv run pytest tests/ -v` → PASS (the chat path issues sequential tool calls; the lock does not change it).

- [ ] **Step 5: Commit**

```bash
git add app/agent/mcp_host.py tests/test_agent/test_mcp_host.py
git commit -m "feat(agent): serialize MCP calls with a lock and add async call_async"
```

---

### Task 4: live-data parsing + `TelemetrySampler`

**Files:**
- Create: `app/telemetry/parse.py`, `app/telemetry/sampler.py`
- Test: `tests/test_telemetry/test_parse.py`, `tests/test_telemetry/test_sampler.py` (create)

**Interfaces:**
- Consumes: nothing (the sampler is decoupled from the host via injected callables).
- Produces:
  - `parse.LiveReadError(Exception)`; `parse.parse_live_data(text: str) -> dict[str, dict | None]` (`{name: {"value","unit"} | None}`; raises `LiveReadError` when `text` is a host sentinel, i.e. not JSON); `parse.parse_supported_pids(text) -> list[dict]`; `parse.parse_vin(text) -> str | None`.
  - `sampler.Subscriber` (`.pids: set[str]`, `.queue: asyncio.Queue`, `.offer(event: dict) -> None` latest-wins).
  - `sampler.TelemetrySampler(call_live, persist, target_hz, min_interval_s)` where `call_live: Callable[[list[str]], Awaitable[dict]]` and `persist: Callable[[dict], None]`. Methods: `subscribe(pids, queue_size) -> Subscriber`, `unsubscribe(sub) -> None`, `subscriber_count: int`, `union_pids: list[str]`, `start() -> None`, `async stop() -> None`; attrs `achieved_hz: float`, `error: str | None`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_telemetry/test_parse.py`:
```python
import json

import pytest

from app.telemetry.parse import LiveReadError, parse_live_data, parse_supported_pids, parse_vin


def test_parse_live_data_maps_names_to_value_unit():
    text = json.dumps([
        {"pid": "0C", "name": "RPM", "value": 820, "unit": "revolutions_per_minute", "timestamp": 1.0},
        {"pid": "0D", "name": "SPEED", "value": 0, "unit": "kph", "timestamp": 1.0},
    ])
    out = parse_live_data(text)
    assert out == {
        "RPM": {"value": 820, "unit": "revolutions_per_minute"},
        "SPEED": {"value": 0, "unit": "kph"},
    }


def test_parse_live_data_error_markers_become_none():
    text = json.dumps([
        {"pid": "0C", "name": "RPM", "value": 820, "unit": "rpm", "timestamp": 1.0},
        {"pid": "05", "name": "COOLANT_TEMP", "error": "NOT_SUPPORTED", "timestamp": 1.0},
    ])
    out = parse_live_data(text)
    assert out["RPM"]["value"] == 820
    assert out["COOLANT_TEMP"] is None


def test_parse_live_data_raises_on_host_sentinel():
    # Host sentinels start with "[" but are NOT valid JSON — must be distinguished by json.loads, not prefix.
    for sentinel in ["[obd unavailable] ...", "[tool error] read_live_data: boom", "[obd error] nope"]:
        with pytest.raises(LiveReadError):
            parse_live_data(sentinel)


def test_parse_supported_pids_and_vin():
    pids = parse_supported_pids(json.dumps([{"pid": "0C", "name": "RPM", "description": "Engine RPM"}]))
    assert pids[0]["name"] == "RPM"
    assert parse_vin(json.dumps({"vin": "WAUZZZ", "protocol": "ISO 15765-4"})) == "WAUZZZ"
    assert parse_vin(json.dumps({"vin": None})) is None
    with pytest.raises(LiveReadError):
        parse_vin("[obd unavailable] x")
```

Create `tests/test_telemetry/test_sampler.py`:
```python
import asyncio

from app.telemetry.sampler import TelemetrySampler


def test_sampler_reads_union_persists_and_fans_out():
    persisted: list[dict] = []

    async def call_live(pids):
        # echo a value per requested pid
        return {p: {"value": len(p), "unit": "x"} for p in pids}

    async def scenario():
        sampler = TelemetrySampler(
            call_live=call_live, persist=persisted.append, target_hz=50.0, min_interval_s=0.0
        )
        a = sampler.subscribe(["RPM"], queue_size=4)
        b = sampler.subscribe(["RPM", "SPEED"], queue_size=4)
        assert sampler.union_pids == ["RPM", "SPEED"]
        sampler.start()
        # collect one sample on each subscriber
        ev_a = await asyncio.wait_for(a.queue.get(), timeout=1.0)
        ev_b = await asyncio.wait_for(b.queue.get(), timeout=1.0)
        await sampler.stop()
        return ev_a, ev_b

    ev_a, ev_b = asyncio.run(scenario())
    assert ev_a["type"] == "sample"
    assert set(ev_a["values"]) == {"RPM"}            # filtered to A's PIDs
    assert set(ev_b["values"]) == {"RPM", "SPEED"}   # filtered to B's PIDs
    assert persisted and set(persisted[0]["values"]) == {"RPM", "SPEED"}  # union persisted


def test_subscriber_offer_is_latest_wins():
    from app.telemetry.sampler import Subscriber

    sub = Subscriber(["RPM"], queue_size=1)
    sub.offer({"seq": 1})
    sub.offer({"seq": 2})  # drops seq 1, keeps newest
    assert sub.queue.qsize() == 1
    assert sub.queue.get_nowait()["seq"] == 2


def test_sampler_reports_error_on_read_failure():
    from app.telemetry.parse import LiveReadError

    async def call_live(pids):
        raise LiveReadError("[tool error] boom")

    async def scenario():
        sampler = TelemetrySampler(call_live=call_live, persist=lambda s: None, target_hz=50.0, min_interval_s=0.0)
        sub = sampler.subscribe(["RPM"], queue_size=4)
        sampler.start()
        ev = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
        await sampler.stop()
        return ev, sampler.error

    ev, err = asyncio.run(scenario())
    assert ev["type"] == "disconnected"
    assert err is not None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `uv run pytest tests/test_telemetry/test_parse.py tests/test_telemetry/test_sampler.py -v`
Expected: FAIL — modules missing.

- [ ] **Step 3: Write the parser**

Create `app/telemetry/parse.py`:
```python
from __future__ import annotations

import json
from typing import Any


class LiveReadError(Exception):
    """The host returned a sentinel string (not JSON) — the adapter call failed."""


def _load(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        # Host sentinels ("[obd unavailable] ...", "[tool error] ...") are not JSON.
        raise LiveReadError(text) from exc


def _as_list(data: Any) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("result", "results", "readings", "data"):
            if isinstance(data.get(key), list):
                return data[key]
    return []


def parse_live_data(text: str) -> dict[str, dict | None]:
    out: dict[str, dict | None] = {}
    for entry in _as_list(_load(text)):
        name = entry.get("name")
        if not name:
            continue
        out[name] = None if "error" in entry else {"value": entry.get("value"), "unit": entry.get("unit")}
    return out


def parse_supported_pids(text: str) -> list[dict]:
    return [
        {"pid": e.get("pid"), "name": e.get("name"), "description": e.get("description")}
        for e in _as_list(_load(text))
        if e.get("name")
    ]


def parse_vin(text: str) -> str | None:
    data = _load(text)
    if isinstance(data, dict):
        return data.get("vin")
    return None
```

- [ ] **Step 4: Write the sampler**

Create `app/telemetry/sampler.py`:
```python
from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable


class Subscriber:
    def __init__(self, pids: list[str], queue_size: int) -> None:
        self.pids: set[str] = set(pids)
        self.queue: asyncio.Queue = asyncio.Queue(maxsize=max(1, queue_size))

    def offer(self, event: dict) -> None:
        # Latest-wins: if full, drop the oldest so a slow consumer never backs up the sampler.
        if self.queue.full():
            try:
                self.queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
        try:
            self.queue.put_nowait(event)
        except asyncio.QueueFull:
            pass


class TelemetrySampler:
    """One async poll loop per adapter. Reads the union of subscribed PIDs each tick,
    persists the full sample, and fans a per-subscriber filtered view out latest-wins."""

    def __init__(
        self,
        call_live: Callable[[list[str]], Awaitable[dict]],
        persist: Callable[[dict], None],
        target_hz: float,
        min_interval_s: float,
    ) -> None:
        self._call_live = call_live
        self._persist = persist
        self._interval = max(1.0 / target_hz if target_hz > 0 else 1.0, min_interval_s)
        self._subscribers: set[Subscriber] = set()
        self._task: asyncio.Task | None = None
        self._seq = 0
        self._t0 = time.monotonic()
        self.achieved_hz: float = 0.0
        self.error: str | None = None

    @property
    def union_pids(self) -> list[str]:
        u: set[str] = set()
        for sub in self._subscribers:
            u |= sub.pids
        return sorted(u)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)

    def subscribe(self, pids: list[str], queue_size: int) -> Subscriber:
        sub = Subscriber(pids, queue_size)
        self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: Subscriber) -> None:
        self._subscribers.discard(sub)

    def start(self) -> None:
        if self._task is None:
            self._t0 = time.monotonic()
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    async def _run(self) -> None:
        next_t = time.monotonic()
        try:
            while True:
                pids = self.union_pids
                if not pids:
                    await asyncio.sleep(self._interval)
                    next_t = time.monotonic()
                    continue
                started = time.monotonic()
                values = await self._call_live(pids)
                dt = time.monotonic() - started
                self.achieved_hz = round(1.0 / dt, 2) if dt > 0 else 0.0
                self._seq += 1
                t_offset_ms = int((time.monotonic() - self._t0) * 1000)
                self._persist({"seq": self._seq, "t_offset_ms": t_offset_ms, "values": values})
                for sub in list(self._subscribers):
                    filtered = {p: values.get(p) for p in sub.pids}
                    sub.offer(
                        {
                            "type": "sample",
                            "seq": self._seq,
                            "t": t_offset_ms,
                            "hz": self.achieved_hz,
                            "values": filtered,
                        }
                    )
                next_t = max(next_t + self._interval, time.monotonic())
                await asyncio.sleep(max(0.0, next_t - time.monotonic()))
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # LiveReadError or anything from call_live
            self.error = str(exc)
            for sub in list(self._subscribers):
                sub.offer({"type": "disconnected", "detail": str(exc)})
```

- [ ] **Step 5: Run the tests + full suite, commit**

Run: `uv run pytest tests/test_telemetry/test_parse.py tests/test_telemetry/test_sampler.py -v` → PASS.
Run: `uv run pytest tests/ -v` → PASS.
```bash
git add app/telemetry/parse.py app/telemetry/sampler.py tests/test_telemetry/test_parse.py tests/test_telemetry/test_sampler.py
git commit -m "feat(telemetry): live-data parsing and the shared async sampler"
```

---

### Task 5: batched `Recorder` + `TelemetryManager`

**Files:**
- Create: `app/telemetry/recorder.py`, `app/telemetry/manager.py`
- Test: `tests/test_telemetry/test_manager.py` (create)

**Interfaces:**
- Consumes: `TelemetrySampler`/`Subscriber` (Task 4), `parse_live_data`/`parse_vin`/`LiveReadError` (Task 4), `LiveSessionRepository`/`LiveSampleRepository` (Task 2), an `ObdMcpHost`-shaped object (only `available: bool` and `async call_async(name, args) -> str` are used — a fake in tests).
- Produces:
  - `recorder.Recorder(session_factory, session_id, batch_size)`: `enqueue(sample: dict) -> None`, `start() -> None`, `async stop() -> int` (flushes the remainder, returns total rows written).
  - `manager.LiveSessionConflict(Exception)` (carries `.active_vehicle_id`).
  - `manager.TelemetryManager(host, session_factory, settings)`: `async subscribe(vehicle_id, pids) -> tuple[int, Subscriber, str | None]` (returns `session_id`, the subscriber, and a `vin_mismatch` detail or `None`); `async unsubscribe(sub) -> None`; `active_vehicle_id: int | None`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_telemetry/test_manager.py`:
```python
import asyncio
import json

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401 — register models
from app.config import Settings
from app.db import Base
from app.models.vehicle import Vehicle
from app.repositories.live_session_repository import LiveSessionRepository
from app.repositories.live_sample_repository import LiveSampleRepository
from app.telemetry.manager import LiveSessionConflict, TelemetryManager


class FakeHost:
    """Async OBD host stub: get_vehicle_info returns a VIN; read_live_data echoes values."""

    def __init__(self, vin="WAUZZZ", available=True):
        self.available = available
        self._vin = vin

    async def call_async(self, name, args):
        if name == "get_vehicle_info":
            return json.dumps({"vin": self._vin})
        if name == "read_live_data":
            return json.dumps([{"name": p, "value": 1, "unit": "x"} for p in args["pids"]])
        return "[obd error] unknown"


def _factory():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_telemetry/test_manager.py -v`
Expected: FAIL — `recorder`/`manager` modules missing.

- [ ] **Step 3: Write the recorder**

Create `app/telemetry/recorder.py`:
```python
from __future__ import annotations

import asyncio

from app.repositories.live_sample_repository import LiveSampleRepository


class Recorder:
    """Drains sample dicts off the sampling loop and batch-writes them with a fresh
    sync Session in a thread executor, so the per-tick DB write is never on the hot path."""

    def __init__(self, session_factory, session_id: int, batch_size: int) -> None:
        self._session_factory = session_factory
        self._session_id = session_id
        self._batch = max(1, batch_size)
        self._queue: asyncio.Queue = asyncio.Queue()
        self._task: asyncio.Task | None = None
        self._written = 0

    def enqueue(self, sample: dict) -> None:
        try:
            self._queue.put_nowait(sample)
        except asyncio.QueueFull:
            pass

    def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._run())

    async def stop(self) -> int:
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        await self._drain()
        return self._written

    async def _run(self) -> None:
        while True:
            first = await self._queue.get()
            buf = [first]
            while len(buf) < self._batch and not self._queue.empty():
                buf.append(self._queue.get_nowait())
            await self._flush(buf)

    async def _drain(self) -> None:
        buf: list[dict] = []
        while not self._queue.empty():
            buf.append(self._queue.get_nowait())
        if buf:
            await self._flush(buf)

    async def _flush(self, buf: list[dict]) -> None:
        await asyncio.get_event_loop().run_in_executor(None, self._write_batch, buf)
        self._written += len(buf)

    def _write_batch(self, buf: list[dict]) -> None:
        session = self._session_factory()
        try:
            LiveSampleRepository(session).bulk_create(
                [{"session_id": self._session_id, **s} for s in buf]
            )
            session.commit()
        finally:
            session.close()
```

- [ ] **Step 4: Write the manager**

Create `app/telemetry/manager.py`:
```python
from __future__ import annotations

import asyncio

from app.config import Settings
from app.repositories.live_session_repository import LiveSessionRepository
from app.telemetry.parse import LiveReadError, parse_live_data, parse_vin
from app.telemetry.recorder import Recorder
from app.telemetry.sampler import Subscriber, TelemetrySampler


class LiveSessionConflict(Exception):
    def __init__(self, active_vehicle_id: int | None) -> None:
        super().__init__(f"A live session is active for vehicle {active_vehicle_id}")
        self.active_vehicle_id = active_vehicle_id


class TelemetryManager:
    """Process-wide owner of the single live session. Enforces one active session,
    wires the host to a shared sampler + recorder, and owns the session-row lifecycle."""

    def __init__(self, host, session_factory, settings: Settings) -> None:
        self._host = host
        self._session_factory = session_factory
        self._settings = settings
        self._guard = asyncio.Lock()
        self._sampler: TelemetrySampler | None = None
        self._recorder: Recorder | None = None
        self._session_id: int | None = None
        self.active_vehicle_id: int | None = None

    def _make_call_live(self):
        async def call_live(pids: list[str]) -> dict:
            return parse_live_data(await self._host.call_async("read_live_data", {"pids": pids}))

        return call_live

    async def _vin_mismatch(self, vehicle_id: int) -> tuple[str | None, str | None]:
        """Returns (scanner_vin, mismatch_detail). Non-blocking — never raises on read failure."""
        try:
            scanner_vin = parse_vin(await self._host.call_async("get_vehicle_info", {}))
        except LiveReadError:
            return None, None
        session = self._session_factory()
        try:
            from app.models.vehicle import Vehicle

            vehicle = session.get(Vehicle, vehicle_id)
            vehicle_vin = vehicle.vin if vehicle else None
        finally:
            session.close()
        if scanner_vin and vehicle_vin and scanner_vin != vehicle_vin:
            return scanner_vin, (
                f"Connected scanner reports VIN {scanner_vin}, "
                f"but this vehicle is recorded as {vehicle_vin}."
            )
        return scanner_vin, None

    async def subscribe(self, vehicle_id: int, pids: list[str]) -> tuple[int, Subscriber, str | None]:
        async with self._guard:
            if self._sampler is not None and self.active_vehicle_id != vehicle_id:
                raise LiveSessionConflict(self.active_vehicle_id)

            mismatch = None
            if self._sampler is None:
                _scanner_vin, mismatch = await self._vin_mismatch(vehicle_id)
                session = self._session_factory()
                try:
                    row = LiveSessionRepository(session).create(
                        vehicle_id=vehicle_id,
                        vin=_scanner_vin,
                        target_hz=self._settings.live_sample_hz,
                        pids=pids,
                    )
                    session.commit()
                    self._session_id = row.id
                finally:
                    session.close()

                self._recorder = Recorder(
                    self._session_factory, self._session_id, self._settings.live_recorder_batch
                )
                self._recorder.start()
                self._sampler = TelemetrySampler(
                    call_live=self._make_call_live(),
                    persist=self._recorder.enqueue,
                    target_hz=self._settings.live_sample_hz,
                    min_interval_s=self._settings.live_min_interval_s,
                )
                self._sampler.start()
                self.active_vehicle_id = vehicle_id

            sub = self._sampler.subscribe(pids, self._settings.live_subscriber_queue)
            return self._session_id, sub, mismatch

    async def unsubscribe(self, sub: Subscriber) -> None:
        async with self._guard:
            if self._sampler is None:
                return
            self._sampler.unsubscribe(sub)
            if self._sampler.subscriber_count > 0:
                return
            achieved = self._sampler.achieved_hz
            status = "error" if self._sampler.error else "ended"
            await self._sampler.stop()
            written = await self._recorder.stop() if self._recorder else 0
            session = self._session_factory()
            try:
                LiveSessionRepository(session).mark_ended(
                    self._session_id, status=status, achieved_hz=achieved, sample_count=written
                )
                session.commit()
            finally:
                session.close()
            self._sampler = None
            self._recorder = None
            self._session_id = None
            self.active_vehicle_id = None
```

- [ ] **Step 5: Run the test + full suite, commit**

Run: `uv run pytest tests/test_telemetry/test_manager.py -v` → PASS.
Run: `uv run pytest tests/ -v` → PASS.
```bash
git add app/telemetry/recorder.py app/telemetry/manager.py tests/test_telemetry/test_manager.py
git commit -m "feat(telemetry): batched recorder and one-session telemetry manager"
```

---

### Task 6: telemetry router + lifespan wiring

**Files:**
- Create: `app/api/routers/telemetry.py`
- Modify: `app/api/main.py` (lifespan creates the manager; include the router)
- Test: `tests/test_api/test_telemetry.py` (create)

**Interfaces:**
- Consumes: `TelemetryManager`/`LiveSessionConflict` (Task 5), `parse_supported_pids` (Task 4), `LiveSessionRepository`/`LiveSampleRepository` (Task 2), `CURATED_PIDS` (Task 1), `get_session` dependency, `app.state.obd_host`, `app.state.telemetry_manager`.
- Produces:
  - `GET /api/vehicles/{id}/live?pids=RPM,SPEED` → `text/event-stream` (`session`, `sample`*, `vin_mismatch`?, `disconnected`/`error`?, `done`); `409` on a second vehicle; an `error` event when no host/manager.
  - `GET /api/vehicles/{id}/supported-pids` → `{curated: [...], supported: [...], available: bool}`.
  - `GET /api/vehicles/{id}/sessions` → list; `GET /api/sessions/{id}` → `{session, samples}`.
  - `app.state.telemetry_manager` set in lifespan (a `TelemetryManager` when `obd_mcp_enabled` and the host started, else `None`).

- [ ] **Step 1: Write the failing test**

Create `tests/test_api/test_telemetry.py`:
```python
import json

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


def test_live_stream_emits_session_and_samples(api_client):
    _seed_vehicle(api_client)
    _install_manager(api_client)

    events = []
    with api_client.stream("GET", "/api/vehicles/1/live?pids=RPM,SPEED") as r:
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:"):].strip()))
            if len([e for e in events if e["type"] == "sample"]) >= 2:
                break  # closing the stream triggers server-side unsubscribe

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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_api/test_telemetry.py -v`
Expected: FAIL — routes/`telemetry_manager` not defined.

- [ ] **Step 3: Write the router**

Create `app/api/routers/telemetry.py`:
```python
import asyncio
import json

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from app.api.deps import get_session
from app.telemetry.manager import LiveSessionConflict
from app.telemetry.parse import LiveReadError, parse_supported_pids
from app.telemetry.pids import CURATED_PIDS
from app.repositories.live_sample_repository import LiveSampleRepository
from app.repositories.live_session_repository import LiveSessionRepository

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
    except LiveReadError:
        supported = []
    return {"available": True, "curated": CURATED_PIDS, "supported": supported}


@router.get("/vehicles/{vehicle_id}/live")
async def live(vehicle_id: int, pids: str, request: Request):
    manager = getattr(request.app.state, "telemetry_manager", None)
    host = getattr(request.app.state, "obd_host", None)
    pid_list = [p.strip() for p in pids.split(",") if p.strip()]

    if manager is None or host is None or not host.available:
        async def err():
            yield _sse({"type": "error", "detail": "OBD tool server not running."})
            yield _sse({"type": "done"})

        return StreamingResponse(err(), media_type="text/event-stream")

    try:
        session_id, sub, mismatch = await manager.subscribe(vehicle_id, pid_list)
    except LiveSessionConflict as exc:
        raise HTTPException(
            status_code=409,
            detail=f"A live session is already active for vehicle {exc.active_vehicle_id}.",
        )

    async def stream():
        try:
            yield _sse({"type": "session", "session_id": session_id, "target_hz": manager._settings.live_sample_hz})
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
        finally:
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
```

- [ ] **Step 4: Wire the router + lifespan**

In `app/api/main.py`:

(a) Add to the routers import line (replace the existing one):
```python
from app.api.routers import vehicles, jobs, documents, chat, scanner, config, telemetry
```

(b) Add the manager import near the top (with the other app imports):
```python
from app.telemetry.manager import TelemetryManager
```

(c) In `lifespan`, set `telemetry_manager` right after the host is stored — replace the OBD block with:
```python
    app.state.obd_host = None
    app.state.telemetry_manager = None
    if settings.obd_mcp_enabled:
        host = build_obd_host(settings)
        if not host.start():
            logger.warning("OBD MCP host failed to start; chat will run without OBD tools")
        app.state.obd_host = host
        if host.available:
            app.state.telemetry_manager = TelemetryManager(
                host, app.state.session_factory, settings
            )
```

(d) In `create_app`, include the router beside the others:
```python
    app.include_router(scanner.router)
    app.include_router(config.router)
    app.include_router(telemetry.router)
```

- [ ] **Step 5: Run the tests + full suite**

Run: `uv run pytest tests/test_api/test_telemetry.py -v` → PASS.
Run: `uv run pytest tests/ -v` → PASS — output pristine, no leaked tasks/warnings.

- [ ] **Step 6: Commit**

```bash
git add app/api/routers/telemetry.py app/api/main.py tests/test_api/test_telemetry.py
git commit -m "feat(api): live telemetry SSE endpoint, supported-pids, and session history"
```

---

## Manual smoke test (after all tasks)

With `.env`: `OPENAI_API_KEY=...`, `OBD_MCP_ENABLED=true`, `OBD_MCP_DIR=/home/mark/repos/OBD-II-MCP-Server`, `OBD_PORT=socket://localhost:35000`, and a running ELM327 simulator (e.g. `elm -s car`) or a real adapter:
```bash
uv run mechanic-sidekick-api
curl -s "localhost:8000/api/vehicles/1/supported-pids"
curl -N "localhost:8000/api/vehicles/1/live?pids=RPM,SPEED,COOLANT_TEMP"
# expect: data: {"type":"session",...} then a stream of data: {"type":"sample","seq":N,"hz":...,"values":{...}}
curl -s "localhost:8000/api/vehicles/1/sessions"     # the recorded session(s)
```

## Self-review

**Spec coverage (design spec §Architecture, §Data model, §Concurrency, §Config, D7–D14):**
- Serialize through one connection + async surface (D7, D14) → Task 3 (lock + `call_async`). ✔
- `read_live_data` poll loop, not `record_session` (D9); adaptive cadence (D13) → Task 4 (`TelemetrySampler`, `next_t = max(...)`, `achieved_hz`). ✔
- One shared sampler, latest-wins queues, off-hot-path recording (D11, D12) → Tasks 4–5 (`Subscriber.offer`, `Recorder` executor batch). ✔
- Async SSE, not sync generator (D10) → Task 6 (`async def` + async generator). ✔
- Per-vehicle Live + VIN check (D2) → Task 5 (`_vin_mismatch`, non-blocking). ✔
- Curated + custom PIDs (D3) → Task 1 `CURATED_PIDS` + Task 6 `supported-pids`. ✔
- Record sessions now (D5) → Tasks 2, 5. ✔
- One active session (spec §Concurrency) → Task 5 `LiveSessionConflict` + Task 6 `409`. ✔
- Out of scope here: ECharts/Vue Live view (Plan B), Phase 3 copilot. Correctly excluded.

**Placeholder scan:** Every code step is complete; every test asserts behavior. No TBD/TODO. ✔

**Type/interface consistency:** `call_async(name, args) -> str` matches between Task 3 (def) and Tasks 5–6 (use). `TelemetrySampler(call_live, persist, target_hz, min_interval_s)` + `Subscriber.queue`/`.offer` match between Task 4 (def) and Task 5 (use). `Recorder(session_factory, session_id, batch_size)` with `enqueue`/`start`/`stop` matches Task 5 internal use. `TelemetryManager.subscribe -> (session_id, Subscriber, mismatch)` / `unsubscribe` / `LiveSessionConflict.active_vehicle_id` match between Task 5 (def) and Task 6 (router). Repo signatures (`create`, `mark_ended`, `bulk_create`, `list_by_session`, `latest_pids`) match between Task 2 (def) and Tasks 5–6 (use). Sample dict shape `{seq, t_offset_ms, values}` is identical across sampler `persist`, recorder `bulk_create`, and the repo. ✔
```
