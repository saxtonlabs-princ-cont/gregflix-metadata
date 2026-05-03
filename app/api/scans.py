from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Query, Request

router = APIRouter(prefix="/scans", tags=["scans"])


@router.post("")
async def trigger_scan(
    request: Request,
    retry_failed: bool = Query(False, description="Retry folders with failed markers instead of skipping open failure issues"),
    reprocess: bool = Query(False, description="Queue folders even when Postgres already has processed state"),
    path: str | None = Query(None, description="Optional single folder path to reconcile, retry, or reprocess"),
) -> dict[str, object]:
    coordinator = request.app.state.scan_coordinator
    return await coordinator.trigger_scan(
        retry_failed=retry_failed,
        reprocess=reprocess,
        folder_path=Path(path).expanduser().resolve() if path else None,
    )


@router.get("/status")
def scan_status(request: Request) -> dict[str, object]:
    coordinator = request.app.state.scan_coordinator
    return coordinator.status()
