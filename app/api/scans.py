from __future__ import annotations

from fastapi import APIRouter, Request

router = APIRouter(prefix="/scans", tags=["scans"])


@router.post("")
async def trigger_scan(request: Request) -> dict[str, object]:
    coordinator = request.app.state.scan_coordinator
    return await coordinator.trigger_scan()


@router.get("/status")
def scan_status(request: Request) -> dict[str, object]:
    coordinator = request.app.state.scan_coordinator
    return coordinator.status()
