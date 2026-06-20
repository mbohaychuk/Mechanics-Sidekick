# Mechanics Sidekick — Live Telemetry Dashboard (Diagnostic Copilot · Phase 2)

**Date:** 2026-06-18
**Status:** Approved design, implementation-ready. This is the **dashboard** increment of the live diagnostic copilot. The proactive LLM session — live commentary, guided "rev it / drive it" actions, and the generated health report — is **Phase 3**, sketched at the end and getting its own spec → plan → build cycle.

## Context

v1 shipped a web app with an agentic Q&A chat that reads the live car through `obd-mcp` as **on-demand tool calls**. This feature adds the first piece of the live diagnostic copilot: a **per-vehicle Live telemetry dashboard** that continuously streams the car's sensor data (PIDs) in real time and **records each session** to the database. Read-only, no LLM. It is the data foundation the diagnostic session (Phase 3) will consume.

The defining constraint that shapes the entire concurrency and streaming design: an **ELM327 OBD-II adapter is a single, serialized hardware resource.** It is a half-duplex command interpreter — it sends one OBD/AT command, waits for the ECU to reply, buffers the response (terminated by `>`), and only then accepts the next command. It physically cannot pipeline or interleave requests, and the serial/socket port has exactly one OS-level owner process. `obd-mcp` owns that port; the backend's `ObdMcpHost` owns the one MCP `ClientSession` to it; `obd-mcp`'s `ObdClient._io_lock` serializes every query. These are not software conveniences — they encode the physics. **Every design decision below follows from "the car is a single serialized sensor."** (This architecture was independently stress-tested by a five-angle review — hardware/protocol, MCP-as-transport, async streaming, an adversarial critic, and an alternatives steelman — whose findings are folded into the Decisions log.)

---

## Decisions log

| # | Decision | Rationale |
|---|---|---|
| D1 | **Build the dashboard first, the LLM diagnostic session (Phase 3) second.** | Incremental: a working live dashboard ships fast and proves the data stream; Phase 3 (commentary, guided actions, report) builds on a proven, recorded stream. |
| D2 | **Per-vehicle "Live" view + VIN safety check.** Open the Live view from a vehicle; on start, read the scanner's VIN (`get_vehicle_info`) and compare to the vehicle's `vin`. Mismatch → non-blocking warning (stream continues); no VIN on file → capture the scanner's. | Prevents showing the wrong car's data without forcing a heavy association model. Single-user, single-scanner → no need for a persisted scanner↔vehicle table yet. |
| D3 | **Curated default PID set + a picker to add/remove any *supported* PID.** Defaults: RPM, speed, coolant temp, intake air temp, MAF, throttle, engine load, timing advance, short- & long-term fuel trims, O2 sensor voltages. Filtered against `list_supported_pids`. | Focused diagnostic vitals out of the box; flexibility to add what a specific diagnosis needs, without a cluttered "everything" dump. |
| D4 | **Layout: dense vitals list + per-row mini chart, plus one large focus chart for pinned PID(s).** | Scannable; scales gracefully as the user adds/removes PIDs; trends visible per value during a rev/drive test. |
| D5 | **Persist (record) each live session now** — a `live_session` + `live_sample` schema. | Phase 3's health report needs recorded time-series; recording the stream now is the natural place, and makes sessions reviewable/replayable immediately. |
| D6 | **Charts: ECharts (via `vue-echarts`).** | The user wants richer visuals than sparklines (zoom, tooltips, multi-series, future gauges). ECharts is the more capable of the full libs; one new frontend dependency, isolated to the Live view. |
| D7 | **Concurrency model: keep everything serialized through the one `obd-mcp` connection.** | Physics: one half-duplex adapter, one OS-owned port. Serialization is *correct*, not a limitation. There is no faster side-channel — a second reader would have to reopen the port (impossible) or reimplement `obd-mcp`. |
| D8 | **MCP is the transport for live telemetry too** (no bypass). | Local stdio JSON-RPC framing is ~1–5 ms; a single PID read is ~50–150 ms (200–400 ms on older protocols). The adapter dominates by 1–2 orders of magnitude, so MCP framing is in the noise. Reusing `obd-mcp` keeps one chokepoint to the bus. |
| D9 | **Live sampling = our own backend poll loop calling `read_live_data` per tick — NOT `obd-mcp`'s `record_session`.** | `read_live_data` returns immediately → per-tick persistence → a crash loses ≤1 tick; open-ended duration. `record_session` is a *batch* tool: it holds the session for its full duration, returns everything only at the end, trips the host's 30 s call timeout, caps at 600 s, and keeps data in `obd-mcp` memory. `record_session` is reserved for Phase 3's bounded "record this 60-second drive." |
| D10 | **Async SSE, not a sync generator in the threadpool.** The live endpoint is `async def` + an async generator on the event loop. | A sync SSE generator pins one of Starlette's ~40 threadpool workers for the whole multi-minute session → reachable exhaustion that also stalls chat/CRUD. Async makes a session cost one coroutine. |
| D11 | **One shared sampler per adapter, fanning out to N subscribers — not one poll loop per browser tab.** | The car is one physical sensor; two tabs polling would double bus load and halve the rate for *identical* data. Sample once, fan out. |
| D12 | **Per-subscriber latest-wins queues (maxsize 1–2); recording off the hot path.** | A slow browser gets the freshest reading, never a backlog, and can never backpressure the adapter (which would stall chat too). Per-tick DB writes go to a separate batched writer, off the sampling loop. |
| D13 | **Adaptive cadence, not hard-coded 1 Hz.** `next_t = max(next_t + interval, now)`; measure real latency; report achieved Hz to the UI. | `read_live_data` reads PIDs sequentially (python-OBD doesn't batch), so a 10–12 PID tick is ~0.8–1.5 s. Honest to the hardware. |
| D14 | **Serialize all MCP calls explicitly (an `asyncio.Lock` in the host) and add an async call surface to `ObdMcpHost`.** | The sampler and a chat OBD call must never hit the session concurrently; the lock matches the bus's serialization and removes any SDK-concurrency doubt. An async `call_async`/subscribe surface lets the live path avoid the per-tick sync `future.result` bridge. Chat ⇄ telemetry contention is then bounded to ~one tick and surfaced in the UI. |

---

## Architecture

Additive to v1; no change to the chat path. New backend pieces under the existing FastAPI app; a new frontend view.

```
Browser (Live view, ECharts) ── SSE ──▶ async live endpoint ──┐
                                                              │ subscribe (asyncio.Queue, latest-wins)
                                            ┌─────────────────▼─────────────────┐
                                            │  TelemetrySampler  (one per adapter)│
                                            │  • poll loop: host.call_async(      │
                                            │      "read_live_data", union(pids)) │   ┌──────────────┐
                                            │  • broadcast → subscriber queues    │   │ batched writer│→ SQLite
                                            │  • enqueue → recording queue ───────┼──▶│ (off hot path)│  (live_sample)
                                            └─────────────────┬─────────────────┘   └──────────────┘
                                                              │  (serialized, asyncio.Lock)
                                                  ObdMcpHost (one MCP session) ──stdio──▶ obd-mcp ──serial/socket──▶ ELM327 ──▶ car
                                                              ▲
                                              chat OBD tool calls (host.call, sync) share the same lock
```

**The defensible chain:** one physical bus → one process (`obd-mcp`) → one MCP session → one serializing lock → one background sampler → N browser subscribers. Every link has a concrete reason and is visible in the code.

### Components

**`ObdMcpHost` additions (`app/agent/mcp_host.py`).**
- An `asyncio.Lock` created on the host's private loop; `_call_async` does `async with self._lock: await self._session.call_tool(...)`. This serializes *all* callers (sync chat `call()` and the async sampler) through the one session — matching the bus, and removing any concurrent-`call_tool` race. Uncontended in the existing sequential chat path, so it does not change current behavior.
- `async def call_async(name, args) -> str` — submits the coroutine to the host loop and returns an awaitable the app-loop sampler awaits directly (`asyncio.wrap_future(run_coroutine_threadsafe(self._call_async(...), self._loop))`). The existing sync `call()` stays for the (sync) chat orchestrator.

**`TelemetrySampler` (`app/telemetry/sampler.py`).** One instance per physical adapter (single-user → at most one active). Owns:
- The poll loop (an `asyncio.Task`): each tick, `await host.call_async("read_live_data", {pids: union_of_subscribed})`, parse, stamp `seq`/`t_offset_ms`, then (a) `put_nowait` to each subscriber's latest-wins queue (drop-oldest on full, filtered to that subscriber's PID subset) and (b) `put` to the recording queue. Adaptive cadence via `next_t = max(next_t + interval, now)`; tracks achieved Hz.
- Subscriber registry (`dict[sub_id, asyncio.Queue]`) with refcounting: lazy-start on first subscriber, stop (and mark the session `ended`) when the last leaves. On read error / host-unavailable: broadcast `disconnected`, mark session `error`, stop.
- A `TelemetryManager` singleton that enforces **one active live session at a time** (a request to start a session for a *different* vehicle while one is active → `409`).

**Recording writer (`app/telemetry/recorder.py`).** Drains the recording queue and batch-inserts `live_sample` rows via `run_in_executor(None, write_batch)` using the existing **sync SQLAlchemy** session (no new DB dependency, e.g. no `aiosqlite`). Off the sampling hot path; recording survives a browser disconnect for the session's lifetime.

**Repositories / models.** `LiveSessionRepository`, `LiveSampleRepository`; models registered in `app/models/__init__.py`.

**Routers (`app/api/routers/telemetry.py`).**
- `GET /api/vehicles/{id}/live?pids=RPM,SPEED,…` → **async** SSE. On open: host available? (else `error`); VIN check (`vin_mismatch` warning if needed); subscribe to the manager's sampler for this vehicle (creating the `live_session` if it's the first subscriber); async-generate `session`/`sample`/`vin_mismatch`/`disconnected`/`error`/`done` events from the subscriber queue. On disconnect (`request.is_disconnected()` / `GeneratorExit`): unsubscribe.
- `GET /api/vehicles/{id}/supported-pids` → `list_supported_pids` (+ flags which curated defaults are supported), for the picker.
- `GET /api/vehicles/{id}/sessions` → list past sessions; `GET /api/sessions/{id}` → a recorded session's full series (replay).

### Data model (schema additions — `create_all`, no Alembic in this project)

- **`live_session`** — `id, vehicle_id (FK), vin (scanner VIN at start, nullable), started_utc, ended_utc (nullable), status (recording|ended|error), target_hz, achieved_hz (nullable), pids_json (selected PIDs), sample_count (default 0)`.
- **`live_sample`** — `id, session_id (FK), seq (monotonic int), recorded_utc, t_offset_ms, values_json` — `{pid: {value, unit}}` for that tick; per-PID `NO_DATA/NOT_SUPPORTED` stored as `null`. One row per tick (~1 Hz → a few hundred rows/session). Mirrors the existing "JSON in SQLite" pattern (embeddings). `seq` also serves as the SSE event id for reconnect.

### SSE event types

`session {session_id, target_hz}` · `sample {seq, t, values}` · `status {achieved_hz}` (periodic) · `vin_mismatch {scanner_vin, vehicle_vin}` · `disconnected {detail}` · `error {detail}` · `done`. Each `sample` event carries an `id:` (the `seq`) so a reconnecting browser can resume; **replay-from-`Last-Event-ID`** (tailing persisted rows after a gap) is a light stretch — minimum is "reconnect and resume the live tail."

### Concurrency & contention (the heart of the design)

- **All adapter access serializes through the host lock** — sampler ticks and chat OBD calls. A chat OBD call can therefore wait up to ~one tick (≤ ~1.5 s for a 10–12 PID set) before it acquires the lock. This is hardware-dictated, not a flaw: two concurrent ELM327 queries would corrupt the frame stream. The UI surfaces it ("live session active — chat may be briefly delayed"); optionally the sampler coarsens its rate while a chat OBD call is pending.
- **No threadpool pinning:** the live endpoint and sampler are async; a session costs a coroutine, not a worker thread.
- **No bus amplification:** one sampler per adapter; extra tabs subscribe to the same stream.
- **No backpressure to the adapter:** latest-wins subscriber queues; a slow client drops stale samples, never stalls the sampler or chat.
- **Persistence off the hot path:** batched writer via executor.

### Config additions (`Settings`)

`LIVE_SAMPLE_HZ` (target, default `1.0`), `LIVE_MIN_INTERVAL_S` (floor, e.g. `0.25`), `LIVE_MAX_PIDS` (cap, e.g. `16`), `LIVE_SUBSCRIBER_QUEUE` (maxsize, default `2`), `LIVE_RECORDER_BATCH` (rows per flush, e.g. `20`). A `CURATED_PIDS` constant (the D3 default set).

### Frontend (Vue, new Live view)

- Route `/vehicles/:id/live`; entry: a "Live data" button on the vehicle detail page + a per-vehicle scanner indicator.
- **`useLiveSession` composable** — opens the SSE stream (generalize the existing fetch-based SSE reader to parse the event types above), holds rolling per-PID buffers (bounded window), exposes connection/VIN/achieved-Hz state, and feeds ECharts (incremental append).
- **`LiveView`** — header (connection + VIN-match status, achieved-vs-target Hz, start/stop); the **dense vitals list** (row per PID: name · value+unit · ECharts mini-line · pin); a **"+ Add PID"** picker over supported PIDs; a large **focus chart** (ECharts, tooltip/zoom) for the pinned PID(s).
- **Past sessions (light):** list a vehicle's recorded sessions; open one to replay its series in the focus chart.
- Charts: `vue-echarts` with `echarts/core` + only the needed components (line chart, tooltip, dataZoom) for a lean bundle.

### Error handling

- Host down / no scanner → "connect a scanner" state, no session created.
- VIN mismatch → non-blocking banner; user proceeds or stops.
- Adapter drops mid-session → `disconnected` event, session `ended`/`error`, UI offers restart.
- Per-PID `NO_DATA/NOT_SUPPORTED` → row shows "—", not an error.
- Second-vehicle live request while one is active → `409` with a clear message.

### Testing

- **Backend:** `TelemetrySampler` + manager with a **fake `ObdMcpHost`** (scripted `read_live_data`, programmable latency): assert session created, union-PID reads, samples broadcast to multiple subscribers, latest-wins drop under a slow subscriber, recording rows persisted (batched), adaptive cadence, VIN-mismatch event, end-on-last-unsubscribe, `409` on second vehicle. The `ObdMcpHost` lock + `call_async` unit-tested (concurrent callers serialize; existing sequential behavior unchanged). Endpoints via `TestClient` (the async SSE consumed and asserted). Repos tested. All hermetic — no real host, no scanner.
- **Frontend (Vitest):** the live SSE parser; `LiveView` rendering streamed samples, the PID picker, connection/VIN/Hz states, ECharts mocked.

---

## Scope boundaries

**In (this increment):** per-vehicle Live view, VIN check, curated + custom PIDs, dense list + ECharts (mini + focus), one shared async sampler, latest-wins streaming, session recording + basic replay, supported-PID picker, the `ObdMcpHost` lock + async surface.

**Out — Phase 3 (the diagnostic copilot):** proactive LLM commentary over the live stream; guided "rev it / drive it" actions; manual-grounded interpretation of readings; automatic diagnosis against the manuals (+ web when uncovered); the generated **health report**. Phase 3 consumes this increment's recorded sessions and may use `obd-mcp`'s `record_session` for bounded guided captures.

**Out — later:** multi-scanner / multi-vehicle concurrent sessions; imperial-units toggle; alert thresholds/alarms; `Last-Event-ID` gap-replay beyond live-tail resume.

## Companion improvement (in the `obd-mcp` repo, not this one)

`obd-mcp` constructs `ObdClient` with `fast=False`, disabling python-OBD's repeat-command (empty-CR) and frame-count shortcuts. Passing **`fast=True`** cuts ~30–50 % off per-PID latency for repeated polls — exactly this workload. Highest-leverage hardware-level win; apply it when `obd-mcp` is next touched (e.g. for Phase 3). Tracked here so it isn't lost.

## Open items (resolved here; noted for the plan)

- Sampler ↔ session lifecycle when all viewers leave: **stop sampler + mark session `ended`** (headless recording is a Phase 3 / guided-test concern).
- PID-selection persistence: defaulted from the vehicle's **last session's `pids_json`** (no separate setting needed).
- Units: **metric** (what python-OBD returns); imperial conversion deferred.
