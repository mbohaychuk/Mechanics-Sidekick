from __future__ import annotations

import asyncio

from app.config import Settings
from app.models.vehicle import Vehicle
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
