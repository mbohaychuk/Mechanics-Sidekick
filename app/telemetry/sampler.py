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
