from __future__ import annotations

import asyncio
import logging

from app.repositories.live_sample_repository import LiveSampleRepository

logger = logging.getLogger(__name__)

# Bound the buffer so a sustained DB write failure can't grow it without limit; ~33 min at 1 Hz.
_MAX_QUEUED_SAMPLES = 2000


class Recorder:
    """Drains sample dicts off the sampling loop and batch-writes them with a fresh
    sync Session in a thread executor, so the per-tick DB write is never on the hot path."""

    def __init__(self, session_factory, session_id: int, batch_size: int) -> None:
        self._session_factory = session_factory
        self._session_id = session_id
        self._batch = max(1, batch_size)
        self._queue: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUED_SAMPLES)
        self._task: asyncio.Task | None = None
        self._written = 0

    def enqueue(self, sample: dict) -> None:
        if self._queue.full():  # latest-wins: drop the oldest so the buffer never grows unbounded
            try:
                self._queue.get_nowait()
            except asyncio.QueueEmpty:
                pass
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
        # A write failure must not kill the drain loop or propagate out of stop() — log and drop
        # the batch, keep recording the rest of the session.
        try:
            await asyncio.get_running_loop().run_in_executor(None, self._write_batch, buf)
            self._written += len(buf)
        except Exception:  # noqa: BLE001
            logger.exception(
                "recorder failed to write %d samples for session %s; dropping batch",
                len(buf), self._session_id,
            )

    def _write_batch(self, buf: list[dict]) -> None:
        session = self._session_factory()
        try:
            LiveSampleRepository(session).bulk_create(
                [{"session_id": self._session_id, **s} for s in buf]
            )
            session.commit()
        finally:
            session.close()
