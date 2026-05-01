from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class QueueJob:
    job_id: str
    folder_path: Path
    library_name: str
    library_category: str


class JobQueue:
    def __init__(self) -> None:
        self._queue: asyncio.Queue[QueueJob] = asyncio.Queue()
        self._scan_lock = asyncio.Lock()
        self._runner_lock = asyncio.Lock()
        self._scan_in_progress = False

    async def begin_scan(self) -> bool:
        async with self._scan_lock:
            if self._scan_in_progress:
                return False
            self._scan_in_progress = True
            return True

    async def end_scan(self) -> None:
        async with self._scan_lock:
            self._scan_in_progress = False

    @property
    def scan_in_progress(self) -> bool:
        return self._scan_in_progress

    @property
    def queue_size(self) -> int:
        return self._queue.qsize()

    async def enqueue(self, job: QueueJob) -> None:
        await self._queue.put(job)

    async def dequeue(self) -> QueueJob:
        return await self._queue.get()

    def task_done(self) -> None:
        self._queue.task_done()

    @property
    def runner_lock(self) -> asyncio.Lock:
        return self._runner_lock
