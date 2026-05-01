import asyncio

import pytest

from app.jobs.queue import JobQueue
from app.jobs.runner import ScanCoordinator


@pytest.mark.asyncio
async def test_queue_rejects_concurrent_scan():
    queue = JobQueue()

    first = await queue.begin_scan()
    second = await queue.begin_scan()

    assert first is True
    assert second is False

    await queue.end_scan()
    third = await queue.begin_scan()
    assert third is True


@pytest.mark.asyncio
async def test_scan_coordinator_rejects_scan_while_jobs_are_running():
    queue = JobQueue()
    coordinator = ScanCoordinator(queue, scanner=None, session_factory=None, ingester=None)
    coordinator._runner_task = asyncio.create_task(asyncio.sleep(0.1))

    try:
        result = await coordinator.trigger_scan()
    finally:
        coordinator._runner_task.cancel()

    assert result["accepted"] is False
    assert result["job_running"] is True
    assert queue.scan_in_progress is False
