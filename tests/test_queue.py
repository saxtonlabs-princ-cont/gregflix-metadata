import pytest

from app.jobs.queue import JobQueue


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
