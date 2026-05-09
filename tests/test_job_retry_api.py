import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.jobs import retry_job
from app.jobs.queue import JobQueue
from app.jobs.runner import ScanCoordinator
from app.models import MetadataJob
from tests.test_scanner import build_config


@pytest.fixture
def retry_context(tmp_path: Path):
    config = build_config(tmp_path)
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    MetadataJob.__table__.create(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, expire_on_commit=False)
    coordinator = ScanCoordinator(JobQueue(), scanner=None, session_factory=session_factory, ingester=None)
    coordinator.ensure_runner_started = lambda: None
    request = SimpleNamespace(
        app=SimpleNamespace(
            state=SimpleNamespace(
                config=config,
                session_factory=session_factory,
                scan_coordinator=coordinator,
            )
        )
    )
    return config, session_factory, request


def create_job(
    session_factory,
    folder_path: Path,
    *,
    status: str = "failed",
    retry_count: int = 0,
    lock_key: str | None = None,
) -> MetadataJob:
    job = MetadataJob(
        id=uuid.uuid4(),
        status=status,
        job_type="metadata_ingest",
        requester="scanner",
        lock_key=lock_key or str(folder_path),
        folder_path=str(folder_path),
        library_name="Movies",
        library_category="movies",
        retry_count=retry_count,
        error="failed",
        error_stage="provider_lookup",
        error_reason="No match",
    )
    with session_factory() as session:
        session.add(job)
        session.commit()
        session.refresh(job)
    return job


@pytest.mark.asyncio
async def test_retry_failed_job_creates_new_pending_job(retry_context):
    config, session_factory, request = retry_context
    folder_path = config.enabled_libraries[0].path / "Failed"
    folder_path.mkdir()
    failed_job = create_job(session_factory, folder_path, retry_count=2)

    response = await retry_job(str(failed_job.id), request)

    assert response["created"] is True
    assert response["job"]["status"] == "pending"
    assert response["job"]["retry_count"] == 3
    with session_factory() as session:
        jobs = session.scalars(select(MetadataJob).order_by(MetadataJob.created_at.asc(), MetadataJob.id.asc())).all()
    assert [job.status for job in jobs] == ["failed", "pending"]
    assert jobs[1].folder_path == failed_job.folder_path
    assert jobs[1].lock_key == failed_job.lock_key
    assert jobs[1].error is None
    assert jobs[1].error_stage is None
    assert jobs[1].error_reason is None


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["pending", "running", "succeeded"])
async def test_retry_non_retryable_job_status_is_rejected(retry_context, status):
    config, session_factory, request = retry_context
    folder_path = config.enabled_libraries[0].path / status
    folder_path.mkdir()
    job = create_job(session_factory, folder_path, status=status)

    with pytest.raises(HTTPException) as exc:
        await retry_job(str(job.id), request)

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_retry_removes_failure_marker(retry_context):
    config, session_factory, request = retry_context
    folder_path = config.enabled_libraries[0].path / "Failed"
    folder_path.mkdir()
    failure_marker = folder_path / config.scanner.failure_marker
    failure_marker.write_text("job_status: failed\n", encoding="utf-8")
    failed_job = create_job(session_factory, folder_path)

    await retry_job(str(failed_job.id), request)

    assert not failure_marker.exists()


@pytest.mark.asyncio
async def test_retry_conflicts_when_success_and_failure_markers_exist(retry_context):
    config, session_factory, request = retry_context
    folder_path = config.enabled_libraries[0].path / "InvalidMarkers"
    folder_path.mkdir()
    (folder_path / config.scanner.success_marker).write_text("job_status: succeeded\n", encoding="utf-8")
    (folder_path / config.scanner.failure_marker).write_text("job_status: failed\n", encoding="utf-8")
    failed_job = create_job(session_factory, folder_path)

    with pytest.raises(HTTPException) as exc:
        await retry_job(str(failed_job.id), request)

    assert exc.value.status_code == 409


@pytest.mark.asyncio
async def test_retry_refuses_paths_outside_enabled_library_roots(retry_context, tmp_path: Path):
    _, session_factory, request = retry_context
    outside = tmp_path / "outside"
    outside.mkdir()
    failed_job = create_job(session_factory, outside)

    with pytest.raises(HTTPException) as exc:
        await retry_job(str(failed_job.id), request)

    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_retry_returns_existing_active_job_for_same_lock_key(retry_context):
    config, session_factory, request = retry_context
    folder_path = config.enabled_libraries[0].path / "Failed"
    folder_path.mkdir()
    failed_job = create_job(session_factory, folder_path)
    active_job = create_job(session_factory, folder_path, status="pending")

    response = await retry_job(str(failed_job.id), request)

    assert response["created"] is False
    assert response["job"]["id"] == str(active_job.id)
    with session_factory() as session:
        job_count = len(session.scalars(select(MetadataJob)).all())
    assert job_count == 2
