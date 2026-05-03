from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import select, text

from app.config import AppConfig, LibraryConfig
from app.models import CanonicalMediaFile, MediaEntity, MetadataIssue, MetadataJob, ProviderMatchCandidate


router = APIRouter(prefix="/metadata", tags=["metadata"])


class PathJobRequest(BaseModel):
    path: str
    requester: str = Field(default="service", max_length=128)


class JobAcceptedResponse(BaseModel):
    job_id: str
    status: str
    job_type: str
    folder_path: str
    library_name: str
    library_category: str


@router.post("/index-path")
async def index_path(payload: PathJobRequest, request: Request) -> dict[str, object]:
    library, folder_path = _validated_library_folder(request.app.state.config, payload.path)
    job = request.app.state.scan_coordinator.enqueue_path_job(
        folder_path=folder_path,
        library_name=library.name,
        library_category=library.category,
        requester=payload.requester,
        job_type="metadata_ingest",
    )
    return _job_response(job)


@router.post("/retry-path")
async def retry_path(payload: PathJobRequest, request: Request) -> dict[str, object]:
    library, folder_path = _validated_library_folder(request.app.state.config, payload.path)
    job = request.app.state.scan_coordinator.enqueue_path_job(
        folder_path=folder_path,
        library_name=library.name,
        library_category=library.category,
        requester=payload.requester,
        job_type="metadata_retry",
    )
    return _job_response(job)


@router.post("/entities/{entity_id}/refresh-provider")
async def refresh_provider_metadata(entity_id: str, request: Request, requester: str = Query("service")) -> dict[str, object]:
    parsed_entity_id = _parse_uuid(entity_id)
    library, folder_path = _folder_for_entity(request, parsed_entity_id)
    job = request.app.state.scan_coordinator.enqueue_path_job(
        folder_path=folder_path,
        library_name=library.name,
        library_category=library.category,
        requester=requester,
        job_type="refresh_provider_metadata",
    )
    return _job_response(job)


@router.post("/entities/{entity_id}/refresh-artwork")
async def refresh_artwork(entity_id: str, request: Request, requester: str = Query("service")) -> dict[str, object]:
    parsed_entity_id = _parse_uuid(entity_id)
    library, folder_path = _folder_for_entity(request, parsed_entity_id)
    job = request.app.state.scan_coordinator.enqueue_path_job(
        folder_path=folder_path,
        library_name=library.name,
        library_category=library.category,
        requester=requester,
        job_type="refresh_artwork",
    )
    return _job_response(job)


@router.get("/issues")
def list_metadata_issues(
    request: Request,
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
) -> list[dict[str, object]]:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        query = select(MetadataIssue).order_by(MetadataIssue.created_at.desc()).limit(limit)
        if status:
            query = select(MetadataIssue).where(MetadataIssue.status == status).order_by(MetadataIssue.created_at.desc()).limit(limit)
        return [_serialize_issue(issue) for issue in session.scalars(query).all()]


@router.get("/diagnostics")
def metadata_diagnostics(
    request: Request,
    entity_id: str | None = Query(None),
    path: str | None = Query(None),
) -> dict[str, object]:
    if not entity_id and not path:
        raise HTTPException(status_code=400, detail="Provide entity_id or path")
    session_factory = request.app.state.session_factory
    parsed_entity_id = _parse_uuid(entity_id) if entity_id else None
    folder_path: Path | None = None
    if path:
        _, folder_path = _validated_library_folder(request.app.state.config, path)

    with session_factory() as session:
        entity = session.get(MediaEntity, parsed_entity_id) if parsed_entity_id else None
        file_prefix = f"{folder_path}%" if folder_path else None
        jobs_query = select(MetadataJob).order_by(MetadataJob.created_at.desc()).limit(20)
        issues_query = select(MetadataIssue).order_by(MetadataIssue.created_at.desc()).limit(50)
        files_query = select(CanonicalMediaFile).limit(50)

        if folder_path:
            jobs_query = select(MetadataJob).where(MetadataJob.folder_path == str(folder_path)).order_by(MetadataJob.created_at.desc()).limit(20)
            issues_query = select(MetadataIssue).where(MetadataIssue.folder_path == str(folder_path)).order_by(MetadataIssue.created_at.desc()).limit(50)
            files_query = select(CanonicalMediaFile).where(CanonicalMediaFile.original_path.like(file_prefix)).limit(50)
        elif parsed_entity_id:
            issues_query = select(MetadataIssue).where(MetadataIssue.entity_id == parsed_entity_id).order_by(MetadataIssue.created_at.desc()).limit(50)
            files_query = select(CanonicalMediaFile).where(CanonicalMediaFile.entity_id == parsed_entity_id).limit(50)

        jobs = session.scalars(jobs_query).all()
        latest_job_ids = [job.id for job in jobs]
        candidates = []
        if latest_job_ids:
            candidates = session.scalars(
                select(ProviderMatchCandidate)
                .where(ProviderMatchCandidate.metadata_job_id.in_(latest_job_ids))
                .order_by(ProviderMatchCandidate.confidence_score.desc())
                .limit(50)
            ).all()
        return {
            "entity": _serialize_entity(entity) if entity else None,
            "path": str(folder_path) if folder_path else None,
            "jobs": [_serialize_job(job) for job in jobs],
            "issues": [_serialize_issue(issue) for issue in session.scalars(issues_query).all()],
            "files": [_serialize_file(media_file) for media_file in session.scalars(files_query).all()],
            "provider_candidates": [_serialize_candidate(candidate) for candidate in candidates],
        }


def _validated_library_folder(config: AppConfig, raw_path: str) -> tuple[LibraryConfig, Path]:
    path = Path(raw_path).expanduser().resolve()
    if not path.exists():
        raise HTTPException(status_code=404, detail="Path does not exist")
    candidate = path if path.is_dir() else path.parent
    for library in config.enabled_libraries:
        library_root = library.path.resolve()
        try:
            relative = candidate.relative_to(library_root)
        except ValueError:
            continue
        if not relative.parts:
            raise HTTPException(status_code=400, detail="Library root itself is not an indexable media folder")
        folder_path = (library_root / relative.parts[0]).resolve()
        if not folder_path.exists() or not folder_path.is_dir():
            raise HTTPException(status_code=404, detail="Media folder does not exist")
        return library, folder_path
    raise HTTPException(status_code=400, detail="Path is outside configured enabled library roots")


def _folder_for_entity(request: Request, entity_id: uuid.UUID) -> tuple[LibraryConfig, Path]:
    session_factory = request.app.state.session_factory
    with session_factory() as session:
        entity = session.get(MediaEntity, entity_id)
        if entity is None:
            raise HTTPException(status_code=404, detail="Entity not found")
        row = session.execute(
            text(
                """
                WITH RECURSIVE descendants AS (
                    SELECT id FROM metadata.media_entity WHERE id = :entity_id
                    UNION ALL
                    SELECT child.id
                    FROM metadata.media_entity child
                    JOIN descendants parent ON child.parent_id = parent.id
                )
                SELECT mf.original_path
                FROM metadata.media_file mf
                JOIN descendants d ON d.id = mf.entity_id
                ORDER BY mf.created_at ASC
                LIMIT 1
                """
            ),
            {"entity_id": entity_id},
        ).first()
        if row is None:
            raise HTTPException(status_code=404, detail="Entity has no known media file path")
    return _validated_library_folder(request.app.state.config, row.original_path)


def _parse_uuid(value: str | None) -> uuid.UUID:
    try:
        return uuid.UUID(str(value))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid UUID") from None


def _job_response(job: MetadataJob | None) -> dict[str, object]:
    if job is None:
        raise HTTPException(status_code=409, detail="Active job already exists")
    return {
        "job_id": str(job.id),
        "status": job.status,
        "job_type": job.job_type,
        "folder_path": job.folder_path,
        "library_name": job.library_name,
        "library_category": job.library_category,
    }


def _serialize_job(job: MetadataJob) -> dict[str, object]:
    return {
        "id": str(job.id),
        "status": job.status,
        "job_type": job.job_type,
        "folder_path": job.folder_path,
        "library_name": job.library_name,
        "library_category": job.library_category,
        "error_stage": job.error_stage,
        "error_reason": job.error_reason,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


def _serialize_issue(issue: MetadataIssue) -> dict[str, object]:
    return {
        "id": str(issue.id),
        "entity_id": str(issue.entity_id) if issue.entity_id else None,
        "metadata_job_id": str(issue.metadata_job_id) if issue.metadata_job_id else None,
        "issue_type": issue.issue_type,
        "severity": issue.severity,
        "status": issue.status,
        "title": issue.title,
        "detail": issue.detail,
        "folder_path": issue.folder_path,
        "payload": issue.payload,
        "created_at": issue.created_at.isoformat() if issue.created_at else None,
    }


def _serialize_entity(entity: MediaEntity) -> dict[str, object]:
    return {
        "id": str(entity.id),
        "entity_type": entity.entity_type,
        "parent_id": str(entity.parent_id) if entity.parent_id else None,
        "title": entity.title,
        "library_category": entity.library_category,
        "release_year": entity.release_year,
    }


def _serialize_file(media_file: CanonicalMediaFile) -> dict[str, object]:
    return {
        "id": str(media_file.id),
        "entity_id": str(media_file.entity_id),
        "original_path": media_file.original_path,
        "sanitized_name": media_file.sanitized_name,
        "season_number": media_file.season_number,
        "episode_number": media_file.episode_number,
    }


def _serialize_candidate(candidate: ProviderMatchCandidate) -> dict[str, object]:
    return {
        "id": str(candidate.id),
        "metadata_job_id": str(candidate.metadata_job_id),
        "provider_name": candidate.provider_name,
        "provider_id": candidate.provider_id,
        "provider_media_type": candidate.provider_media_type,
        "title": candidate.title,
        "release_year": candidate.release_year,
        "confidence_score": candidate.confidence_score,
        "selected": candidate.selected,
        "raw_score_components": candidate.raw_score_components,
    }
