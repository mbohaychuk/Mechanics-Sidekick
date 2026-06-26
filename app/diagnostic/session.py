from __future__ import annotations

import asyncio
import json
import logging
import time
from collections.abc import AsyncIterator

from app.diagnostic.anomaly import evaluate, evaluate_window

logger = logging.getLogger(__name__)
from app.diagnostic.commentary import summarize_window
from app.diagnostic.protocol import ProtocolRunner, safe_adhoc_step
from app.diagnostic.report import Finding, HealthReport, report_to_json
from app.repositories.diagnostic_session_repository import DiagnosticSessionRepository
from app.repositories.live_sample_repository import LiveSampleRepository


class DiagnosticSessionRunner:
    def __init__(
        self, manager, session_factory, vehicle_id, vehicle_label, vehicle_make, protocol,
        commentary, diagnoser_factory, report_builder, settings,
    ) -> None:
        self._manager = manager
        self._session_factory = session_factory
        self._vehicle_id = vehicle_id
        self._vehicle_label = vehicle_label
        self._vehicle_make = vehicle_make
        self._protocol = protocol
        self._commentary = commentary
        self._diagnoser_factory = diagnoser_factory
        self._report_builder = report_builder
        self._settings = settings
        self._runner = ProtocolRunner(protocol, settings.diag_max_adhoc_steps)
        self._window: list[dict] = []
        self._commentary_log: list[dict] = []
        self._flag_keys: set[str] = set()
        # None = not read / read failed (keep distinct from [] = read OK, no codes — never
        # turn a failed read into a fabricated all-clear). Set once at session start.
        self._dtcs: list[dict] | None = None

    def _all_pids(self) -> list[str]:
        pids: set[str] = set()
        for step in self._protocol.steps:
            if step.target:
                pids.add(step.target.pid)
            pids.update(step.capture_pids)
        return sorted(pids)

    async def run(self) -> AsyncIterator[dict]:
        loop = asyncio.get_running_loop()
        pids = self._all_pids()
        diag_id: int | None = None
        sub = None
        try:
            live_session_id, sub, mismatch = await self._manager.subscribe(self._vehicle_id, pids)
            diag_id = await loop.run_in_executor(
                None, self._create_row, live_session_id
            )
            session_event = {
                "type": "session", "diagnostic_session_id": diag_id,
                "live_session_id": live_session_id,
                "protocol": [{"id": s.id, "label": s.label, "instruction": s.instruction}
                             for s in self._protocol.steps],
            }
            if mismatch:
                session_event["vin_mismatch"] = mismatch
            yield session_event

            # Announce the first step as active immediately so the coach card + active highlight
            # render at session start (otherwise step 1 stays 'pending' until it completes, and an
            # incomplete run would never show a coach card at all).
            first = self._runner.current()
            if first is not None:
                yield self._step_event(first)

            # Step 0 of any real diagnosis: pull stored + pending trouble codes once, up front, so
            # the operator sees them immediately (read AFTER announcing step 1 so a slow adapter read
            # never delays the coach card). Advisory — a failed read just shows as "unavailable".
            self._dtcs = await self._manager.read_dtcs(self._vehicle_make)
            yield {"type": "codes", "available": self._dtcs is not None,
                   "codes": self._dtcs or [], "count": len(self._dtcs or [])}

            last_comment = time.monotonic()
            stall_ticks = 0
            while True:
                try:
                    event = await asyncio.wait_for(sub.queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    stall_ticks += 1
                    # Stop once the protocol is done, or if the live feed has stalled (operator
                    # walked away / adapter went quiet) — never hang waiting for a step forever.
                    if self._runner.is_complete() or stall_ticks >= self._settings.diag_stall_ticks:
                        break
                    continue
                stall_ticks = 0

                if event.get("type") == "disconnected":
                    break
                if event.get("type") != "sample":
                    continue

                yield event
                values, seq, t_ms = event["values"], event["seq"], event["t"]
                self._window.append({"seq": seq, "t": t_ms, "values": values})

                advanced = self._runner.offer(values, seq, t_ms)
                if advanced is not None:
                    yield self._step_event(advanced)
                    nxt = self._runner.current()
                    if nxt is not None:
                        yield self._step_event(nxt)
                else:
                    progress = self._runner.progress(values, t_ms)
                    if progress is not None:
                        yield {"type": "step_progress", **progress}

                for flag in evaluate(values, self._settings):
                    key = f"{flag.system}:{flag.pid}"
                    if key not in self._flag_keys:
                        self._flag_keys.add(key)
                        yield {"type": "anomaly", "system": flag.system,
                               "severity": flag.severity, "pid": flag.pid, "detail": flag.detail}

                now = time.monotonic()
                if now - last_comment >= self._settings.diag_commentary_interval_s:
                    last_comment = now
                    async for ev in self._emit_commentary(loop):
                        yield ev

                if self._runner.is_complete():
                    break

            async for ev in self._finalize(loop, diag_id):
                yield ev
            yield {"type": "done"}
        except Exception:  # noqa: BLE001 — surface as an error event, never crash the stream
            logger.exception(
                "Diagnostic session failed (vehicle=%s, diag_id=%s)", self._vehicle_id, diag_id
            )
            if diag_id is not None:
                await loop.run_in_executor(None, self._error_row, diag_id)
            # Generic detail only — never ship raw exception text to the browser.
            yield {"type": "error", "detail": "The diagnostic run hit an internal error and was stopped."}
        finally:
            if sub is not None:
                await self._manager.unsubscribe(sub)

    def _step_event(self, st) -> dict:
        return {"type": "step", "index": st.index, "total": st.total, "id": st.step.id,
                "label": st.step.label, "instruction": st.step.instruction,
                "state": st.state, "adhoc": st.step.adhoc}

    async def _emit_commentary(self, loop) -> AsyncIterator[dict]:
        window = summarize_window(self._window, self._all_pids(),
                                  self._settings.diag_commentary_max_points)
        flags = evaluate(self._window[-1]["values"], self._settings) if self._window else []
        step = self._runner.current()
        commentary = await loop.run_in_executor(
            None, self._commentary.comment, window, step, flags, self._vehicle_label
        )
        if commentary.comment:
            t_ms = self._window[-1]["t"] if self._window else 0
            self._commentary_log.append({"t": t_ms, "text": commentary.comment})
            yield {"type": "commentary", "text": commentary.comment, "t": t_ms}
        if commentary.adapt:
            adhoc = safe_adhoc_step(commentary.adapt)
            if adhoc is not None and self._runner.insert_adhoc(adhoc):
                cur = self._runner.current()
                if cur is not None:
                    yield self._step_event(cur)

    async def _finalize(self, loop, diag_id) -> AsyncIterator[dict]:
        yield {"type": "generating"}  # phase 3: announce report generation before the LLM call
        report_json = await loop.run_in_executor(None, self._build_and_persist, diag_id)
        yield {"type": "report", "overall_status": report_json["overall_status"],
               "summary": report_json["summary"], "findings": report_json["findings"]}

    def _create_row(self, live_session_id) -> int:
        session = self._session_factory()
        try:
            row = DiagnosticSessionRepository(session).create(
                vehicle_id=self._vehicle_id, live_session_id=live_session_id,
                protocol_name=self._protocol.name,
            )
            session.commit()
            return row.id
        finally:
            session.close()

    def _error_row(self, diag_id) -> None:
        session = self._session_factory()
        try:
            DiagnosticSessionRepository(session).mark_error(diag_id)
            session.commit()
        finally:
            session.close()

    def _build_and_persist(self, diag_id) -> dict:
        session = self._session_factory()
        try:
            row = DiagnosticSessionRepository(session).get_by_id(diag_id)
            live_session_id = row.live_session_id if row else None
            recorded = []
            if live_session_id is not None:
                recorded = [
                    {"seq": s.seq, "t": s.t_offset_ms, "values": json.loads(s.values_json)}
                    for s in LiveSampleRepository(session).list_by_session(live_session_id)
                ]

            steps_done = any(s.state == "done" for s in self._runner.completed)
            read_failed = self._dtcs is None  # None = read failed; [] = read OK, no codes

            # Truly nothing to interpret: no guided step was held AND the code read also failed.
            # Report "incomplete" honestly (never a default "good") and skip the LLM. A successful
            # read — even a clean one ([]) — is a real result, so it takes us past this guard.
            if not steps_done and read_failed:
                report = HealthReport(
                    overall_status="incomplete",
                    summary="The health check didn't complete a single guided step, so there isn't "
                            "enough live data to assess the vehicle. Re-run with the engine running "
                            "and hold each step until it's detected.",
                    findings=[],
                )
                report_json = report_to_json(report)
                DiagnosticSessionRepository(session).complete(
                    diag_id, overall_status=report.overall_status, summary=report.summary,
                    report_json=json.dumps(report_json),
                    commentary_json=json.dumps(self._commentary_log),
                )
                session.commit()
                return report_json

            diagnoser = self._diagnoser_factory(session)
            dtc_findings = [diagnoser.diagnose_code(c, self._vehicle_label) for c in (self._dtcs or [])]
            # Without a held step we have no live data to call any system "good".
            good_systems, diagnoses = self._analyze(diagnoser, recorded) if steps_done else ({}, [])

            # Carry the DTC read OUTCOME into the durable report, not just the live stream — the
            # None/[] distinction must survive here too. A failed read becomes a warn finding so the
            # report can never read as a clean all-clear for a scan that silently failed; a clean
            # read is stated explicitly as a good system.
            extra: list[Finding] = []
            if read_failed:
                extra.append(Finding(
                    system="codes", severity="warn",
                    observation="Couldn't read stored or pending trouble codes from the scanner; "
                                "this report does not reflect a DTC scan.",
                ))
            elif self._dtcs == []:
                good_systems = {**good_systems, "codes": "No stored or pending trouble codes."}
            report = self._report_builder.build(
                self._vehicle_label, good_systems, dtc_findings + extra + diagnoses)
            report_json = report_to_json(report)
            DiagnosticSessionRepository(session).complete(
                diag_id, overall_status=report.overall_status, summary=report.summary,
                report_json=json.dumps(report_json),
                commentary_json=json.dumps(self._commentary_log),
            )
            session.commit()
            return report_json
        finally:
            session.close()

    def _analyze(self, diagnoser, recorded) -> tuple[dict, list]:
        # v1 always analyzes the full authoritative recording fetched from the DB, not subsets
        # bounded by each step's seq_start/seq_end — those ranges are tracked but reserved for
        # future per-step drill-down analysis and are not load-bearing here.
        flags = list(evaluate_window(recorded, self._settings))
        seen = set()
        for s in recorded:
            for f in evaluate(s["values"], self._settings):
                if f"{f.system}:{f.pid}" not in seen:
                    seen.add(f"{f.system}:{f.pid}")
                    flags.append(f)

        diagnoses = [diagnoser.diagnose(f, self._vehicle_label) for f in flags]

        flagged_systems = {f.system for f in flags}
        monitored = {"fuel": "Fuel trims stayed within range.",
                     "cooling": "Coolant temperature stayed within range.",
                     "o2": "O2 sensor switching looked normal.",
                     "idle": "Idle speed was stable."}
        # Only call a system healthy if it was ACTUALLY measured — never report "good" for a system
        # whose PIDs never appeared in the recording (that would be a fabricated all-clear).
        system_pids = {"fuel": ("SHORT_FUEL_TRIM_1", "LONG_FUEL_TRIM_1"), "cooling": ("COOLANT_TEMP",),
                       "o2": ("O2_B1S1", "O2_B1S2"), "idle": ("RPM",)}
        observed = {pid for s in recorded for pid, v in s["values"].items()
                    if v is not None and v.get("value") is not None}
        good_systems = {sys: obs for sys, obs in monitored.items()
                        if sys not in flagged_systems and any(p in observed for p in system_pids[sys])}
        return good_systems, diagnoses
