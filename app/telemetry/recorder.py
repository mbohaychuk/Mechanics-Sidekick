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
        # Session + connection are acquired here (event-loop thread) so that
        # SingletonThreadPool assigns the connection from THIS thread's slot —
        # the slot that has the tables. check_same_thread=False then allows the
        # executor thread to use the already-checked-out connection safely.
        session = self._session_factory()
        session.connection()  # force checkout on the event-loop thread
        await asyncio.get_event_loop().run_in_executor(None, self._write_batch, session, buf)
        self._written += len(buf)

    def _write_batch(self, session, buf: list[dict]) -> None:
        try:
            LiveSampleRepository(session).bulk_create(
                [{"session_id": self._session_id, **s} for s in buf]
            )
            session.commit()
        finally:
            session.close()
