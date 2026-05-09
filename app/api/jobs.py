from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.api.metadata import _validated_library_folder
from app.models import MetadataJob

router = APIRouter(prefix="/jobs", tags=["jobs"])

RETRYABLE_STATUSES = {"failed", "cancelled", "stale"}


@router.get("")
def list_jobs(request: Request) -> list[dict[str, object]]:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        jobs = session.scalars(select(MetadataJob).order_by(MetadataJob.created_at.desc()).limit(50)).all()
        return [_serialize_job(job) for job in jobs]


@router.get("/{job_id}")
def get_job(job_id: str, request: Request) -> dict[str, object]:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        try:
            parsed_job_id = uuid.UUID(job_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Job not found") from None
        job = session.get(MetadataJob, parsed_job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        return _serialize_job(job)


@router.post("/{job_id}/retry")
async def retry_job(job_id: str, request: Request) -> dict[str, object]:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        try:
            parsed_job_id = uuid.UUID(job_id)
        except ValueError:
            raise HTTPException(status_code=404, detail="Job not found") from None
        job = session.get(MetadataJob, parsed_job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")
        if job.status not in RETRYABLE_STATUSES:
            raise HTTPException(status_code=409, detail=f"Job status {job.status!r} is not retryable")

        folder_path = _validate_retry_folder(request, job.folder_path)
        _remove_failure_marker(request, folder_path)
        retry, created = request.app.state.scan_coordinator.retry_job(job, requester="retry")
        return {"created": created, "job": _serialize_job(retry)}


def _serialize_job(job: MetadataJob) -> dict[str, object]:
    return {
        "id": str(job.id),
        "status": job.status,
        "job_type": job.job_type,
        "requester": job.requester,
        "lock_key": job.lock_key,
        "folder_path": job.folder_path,
        "library_name": job.library_name,
        "library_category": job.library_category,
        "media_shape": job.media_shape,
        "retry_count": job.retry_count,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "claimed_at": job.claimed_at.isoformat() if job.claimed_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
        "error": job.error,
        "error_stage": job.error_stage,
        "error_reason": job.error_reason,
        "stale_detected_at": job.stale_detected_at.isoformat() if job.stale_detected_at else None,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "updated_at": job.updated_at.isoformat() if job.updated_at else None,
    }


def _validate_retry_folder(request: Request, raw_folder_path: str) -> Path:
    _, folder_path = _validated_library_folder(request.app.state.config, raw_folder_path)
    if str(folder_path) != str(Path(raw_folder_path).expanduser().resolve()):
        raise HTTPException(status_code=400, detail="Job folder path is not a top-level media folder")

    success_marker = folder_path / request.app.state.config.scanner.success_marker
    failure_marker = folder_path / request.app.state.config.scanner.failure_marker
    if success_marker.exists() and failure_marker.exists():
        raise HTTPException(status_code=409, detail="Folder has both success and failure markers; resolve marker conflict before retry")
    return folder_path


def _remove_failure_marker(request: Request, folder_path: Path) -> None:
    failure_marker = folder_path / request.app.state.config.scanner.failure_marker
    if failure_marker.exists():
        failure_marker.unlink()
