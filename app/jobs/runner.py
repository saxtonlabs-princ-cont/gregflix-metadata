from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from app.jobs.queue import JobQueue
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

    async def trigger_scan(
        self,
        *,
        retry_failed: bool = False,
        reprocess: bool = False,
        folder_path: Path | None = None,
    ) -> dict[str, object]:
        scan_started = await self.queue.begin_scan()
        if not scan_started:
            return {
                "accepted": False,
                "message": "Scan already in progress",
                "scan_in_progress": True,
                "queue_size": self.pending_job_count(),
            }

        logger.info("scan started", extra={"event": "scan_started"})
        try:
            summary = self.scanner.scan_all(retry_failed=retry_failed, reprocess=reprocess, folder_path=folder_path)
            created_count = 0
            duplicate_count = 0
            for candidate in summary.queued:
                requester = "retry" if retry_failed else "api" if folder_path is not None or reprocess else "scanner"
                job_id = self._create_pending_job(
                    str(candidate.folder_path),
                    candidate.library_name,
                    candidate.library_category,
                    requester=requester,
                )
                if job_id is None:
                    duplicate_count += 1
                else:
                    created_count += 1
            self.ensure_runner_started()
            logger.info("scan completed summary", extra={"event": "scan_completed_summary", "count": len(summary.queued)})
            return {
                "accepted": True,
                "queued_count": created_count,
                "duplicate_active_jobs": duplicate_count,
                "skipped_success": summary.skipped_success,
                "skipped_failure": summary.skipped_failure,
                "skipped_invalid": summary.skipped_invalid,
                "reconciled_existing": summary.reconciled_existing,
                "issues_created": summary.issues_created,
                "queue_size": self.pending_job_count(),
            }
        finally:
            await self.queue.end_scan()

    async def _run_queue(self) -> None:
        async with self.queue.runner_lock:
            while True:
                job = self._claim_next_pending_job()
                if job is None:
                    return
                await self.ingester.ingest(
                    IngestRequest(
                        folder_path=Path(job.folder_path),
                        library_name=job.library_name,
                        library_category=job.library_category,
                        job_id=str(job.id),
                    )
                )

    def status(self) -> dict[str, object]:
        runner_active = self._runner_task is not None and not self._runner_task.done()
        return {
            "scan_in_progress": self.queue.scan_in_progress,
            "queue_size": self.pending_job_count(),
            "pending_jobs": self.pending_job_count(),
            "running_jobs": self.running_job_count(),
            "job_running": runner_active,
        }

    def recover_stale_running_jobs(self) -> int:
        if self.session_factory is None:
            return 0
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            jobs = session.scalars(select(MetadataJob).where(MetadataJob.status == "running")).all()
            for job in jobs:
                job.status = "failed"
                job.finished_at = now
                job.stale_detected_at = now
                job.error_stage = "startup_recovery"
                job.error_reason = "Application restarted while job was running; job marked failed for explicit retry"
                job.error = job.error_reason
                session.add(job)
            session.commit()
            return len(jobs)

    def pending_job_count(self) -> int:
        if self.session_factory is None:
            return 0
        with self.session_factory() as session:
            return int(session.scalar(select(func.count()).select_from(MetadataJob).where(MetadataJob.status == "pending")) or 0)

    def running_job_count(self) -> int:
        if self.session_factory is None:
            return 0
        with self.session_factory() as session:
            return int(session.scalar(select(func.count()).select_from(MetadataJob).where(MetadataJob.status == "running")) or 0)

    def enqueue_path_job(
        self,
        *,
        folder_path: Path,
        library_name: str,
        library_category: str,
        requester: str,
        job_type: str = "metadata_ingest",
    ) -> MetadataJob | None:
        job_id = self._create_pending_job(
            str(folder_path),
            library_name,
            library_category,
            requester=requester,
            job_type=job_type,
        )
        if job_id is None:
            with self.session_factory() as session:
                return session.scalar(
                    select(MetadataJob).where(
                        MetadataJob.lock_key == str(folder_path),
                        MetadataJob.status.in_(("pending", "running")),
                    )
                )
        self.ensure_runner_started()
        with self.session_factory() as session:
            return session.get(MetadataJob, uuid.UUID(job_id))

    def retry_job(self, job: MetadataJob, *, requester: str | None = None) -> tuple[MetadataJob, bool]:
        with self.session_factory() as session:
            active_job = session.scalar(
                select(MetadataJob).where(
                    MetadataJob.lock_key == job.lock_key,
                    MetadataJob.status.in_(("pending", "running")),
                )
            )
            if active_job is not None:
                return active_job, False

            retry = MetadataJob(
                id=uuid.uuid4(),
                status="pending",
                job_type=job.job_type,
                requester=requester or job.requester,
                lock_key=job.lock_key,
                folder_path=job.folder_path,
                library_name=job.library_name,
                library_category=job.library_category,
                media_shape=job.media_shape,
                retry_count=(job.retry_count or 0) + 1,
            )
            session.add(retry)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                active_job = session.scalar(
                    select(MetadataJob).where(
                        MetadataJob.lock_key == job.lock_key,
                        MetadataJob.status.in_(("pending", "running")),
                    )
                )
                if active_job is not None:
                    return active_job, False
                raise
            session.refresh(retry)

        self.ensure_runner_started()
        return retry, True

    def ensure_runner_started(self) -> None:
        if self._runner_task is None or self._runner_task.done():
            if self.pending_job_count() > 0:
                self._runner_task = asyncio.create_task(self._run_queue())

    def _create_pending_job(
        self,
        folder_path: str,
        library_name: str,
        library_category: str,
        requester: str,
        job_type: str = "metadata_ingest",
    ) -> str | None:
        with self.session_factory() as session:
            existing = session.scalar(
                select(MetadataJob.id).where(
                    MetadataJob.lock_key == folder_path,
                    MetadataJob.status.in_(("pending", "running")),
                )
            )
            if existing is not None:
                return None
            retry_count = int(
                session.scalar(select(func.coalesce(func.max(MetadataJob.retry_count), 0)).where(MetadataJob.lock_key == folder_path))
                or 0
            )
            if requester in {"api", "retry"}:
                retry_count += 1
            job = MetadataJob(
                id=uuid.uuid4(),
                status="pending",
                job_type=job_type,
                requester=requester,
                lock_key=folder_path,
                folder_path=folder_path,
                library_name=library_name,
                library_category=library_category,
                retry_count=retry_count,
            )
            session.add(job)
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                return None
        return str(job.id)

    def _claim_next_pending_job(self) -> MetadataJob | None:
        now = datetime.now(timezone.utc)
        with self.session_factory() as session:
            job = session.scalar(
                select(MetadataJob)
                .where(MetadataJob.status == "pending")
                .order_by(MetadataJob.created_at.asc(), MetadataJob.id.asc())
                .with_for_update(skip_locked=True)
                .limit(1)
            )
            if job is None:
                return None
            job.status = "running"
            job.started_at = now
            job.claimed_at = now
            job.error = None
            job.error_stage = None
            job.error_reason = None
            session.add(job)
            session.commit()
            session.refresh(job)
            return job
