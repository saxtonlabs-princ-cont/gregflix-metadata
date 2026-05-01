from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone

from sqlalchemy.orm import sessionmaker

from app.jobs.queue import JobQueue, QueueJob
from app.models import MetadataJob
from app.services.metadata_ingester import IngestRequest, MetadataIngester
from app.services.scanner import LibraryScanner


logger = logging.getLogger(__name__)


class ScanCoordinator:
    def __init__(self, queue: JobQueue, scanner: LibraryScanner, session_factory: sessionmaker, ingester: MetadataIngester) -> None:
        self.queue = queue
        self.scanner = scanner
        self.session_factory = session_factory
        self.ingester = ingester
        self._runner_task: asyncio.Task | None = None

    async def trigger_scan(self) -> dict[str, object]:
        scan_started = await self.queue.begin_scan()
        if not scan_started:
            return {
                "accepted": False,
                "message": "Scan already in progress",
                "scan_in_progress": True,
                "queue_size": self.queue.queue_size,
            }

        logger.info("scan started", extra={"event": "scan_started"})
        try:
            if self._runner_task is not None and not self._runner_task.done():
                return {
                    "accepted": False,
                    "message": "Metadata jobs are already running",
                    "scan_in_progress": False,
                    "queue_size": self.queue.queue_size,
                    "job_running": True,
                }

            summary = self.scanner.scan_all()
            for candidate in summary.queued:
                job_id = self._create_job_record(str(candidate.folder_path), candidate.library_name, candidate.library_category)
                await self.queue.enqueue(
                    QueueJob(
                        job_id=job_id,
                        folder_path=candidate.folder_path,
                        library_name=candidate.library_name,
                        library_category=candidate.library_category,
                    )
                )
            if self._runner_task is None or self._runner_task.done():
                self._runner_task = asyncio.create_task(self._run_queue())
            logger.info("scan completed summary", extra={"event": "scan_completed_summary", "count": len(summary.queued)})
            return {
                "accepted": True,
                "queued_count": len(summary.queued),
                "skipped_success": summary.skipped_success,
                "skipped_failure": summary.skipped_failure,
                "skipped_invalid": summary.skipped_invalid,
                "queue_size": self.queue.queue_size,
            }
        finally:
            await self.queue.end_scan()

    async def _run_queue(self) -> None:
        async with self.queue.runner_lock:
            while self.queue.queue_size > 0:
                job = await self.queue.dequeue()
                self._mark_job_running(job.job_id)
                await self.ingester.ingest(
                    IngestRequest(
                        folder_path=job.folder_path,
                        library_name=job.library_name,
                        library_category=job.library_category,
                        job_id=job.job_id,
                    )
                )
                self.queue.task_done()

    def status(self) -> dict[str, object]:
        runner_active = self._runner_task is not None and not self._runner_task.done()
        return {
            "scan_in_progress": self.queue.scan_in_progress,
            "queue_size": self.queue.queue_size,
            "job_running": runner_active,
        }

    def _create_job_record(self, folder_path: str, library_name: str, library_category: str) -> str:
        job = MetadataJob(
            id=uuid.uuid4(),
            status="queued",
            folder_path=folder_path,
            library_name=library_name,
            library_category=library_category,
        )
        with self.session_factory() as session:
            session.add(job)
            session.commit()
        return str(job.id)

    def _mark_job_running(self, job_id: str) -> None:
        with self.session_factory() as session:
            job = session.get(MetadataJob, uuid.UUID(job_id))
            if job is None:
                return
            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            session.add(job)
            session.commit()
