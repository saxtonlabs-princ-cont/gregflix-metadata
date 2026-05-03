import asyncio

import pytest

from app.jobs.queue import JobQueue
from app.jobs.runner import ScanCoordinator
from app.services.scanner import ScanSummary


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
async def test_scan_coordinator_allows_scan_while_jobs_are_running():
    queue = JobQueue()

    class EmptyScanner:
        def scan_all(self, **kwargs):
            return ScanSummary(queued=[], skipped_success=0, skipped_failure=0, skipped_invalid=0)

    coordinator = ScanCoordinator(queue, scanner=EmptyScanner(), session_factory=None, ingester=None)
    coordinator._runner_task = asyncio.create_task(asyncio.sleep(0.1))

    try:
        result = await coordinator.trigger_scan()
    finally:
        coordinator._runner_task.cancel()

    assert result["accepted"] is True
    assert result["queued_count"] == 0
    assert queue.scan_in_progress is False
