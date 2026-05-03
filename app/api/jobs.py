from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import select

from app.models import MetadataJob

router = APIRouter(prefix="/jobs", tags=["jobs"])


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
