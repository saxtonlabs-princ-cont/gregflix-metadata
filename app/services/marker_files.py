from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml


@dataclass(frozen=True)
class MarkerState:
    success_exists: bool
    failure_exists: bool

    @property
    def is_invalid(self) -> bool:
        return self.success_exists and self.failure_exists

    @property
    def should_skip(self) -> bool:
        return self.success_exists or self.failure_exists or self.is_invalid


def detect_marker_state(folder_path: Path, success_marker: str, failure_marker: str) -> MarkerState:
    success_exists = (folder_path / success_marker).exists()
    failure_exists = (folder_path / failure_marker).exists()
    return MarkerState(success_exists=success_exists, failure_exists=failure_exists)


def read_marker_file(folder_path: Path, marker_name: str) -> dict[str, Any]:
    marker_path = folder_path / marker_name
    if not marker_path.exists():
        return {}
    payload = yaml.safe_load(marker_path.read_text(encoding="utf-8")) or {}
    return payload if isinstance(payload, dict) else {}


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def build_failure_marker_content(
    *,
    library_name: str,
    library_category: str,
    folder_path: Path,
    raw_folder_name: str,
    raw_filenames: list[str],
    failure_stage: str,
    failure_reason: str,
    extracted_candidate_title: str | None = None,
    exception: Exception | None = None,
    provider_response_count: int | None = None,
    job_id: str | None = None,
    metadata_issue_id: str | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "job_status": "failed",
        "job_id": job_id,
        "metadata_issue_id": metadata_issue_id,
        "failed_at": _timestamp(),
        "library_name": library_name,
        "library_category": library_category,
        "original_folder_path": str(folder_path),
        "raw_folder_name": raw_folder_name,
        "raw_filenames_considered": raw_filenames,
        "extracted_candidate_title": extracted_candidate_title,
        "failure_stage": failure_stage,
        "failure_reason": failure_reason,
        "provider_response_count": provider_response_count,
    }
    if exception is not None:
        payload["exception"] = {
            "type": exception.__class__.__name__,
            "message": str(exception),
        }
    return payload


def build_success_marker_content(
    *,
    library_name: str,
    library_category: str,
    folder_path: Path,
    media_shape: str,
    resolved_title: str,
    provider_name: str,
    provider_id: str,
    extracted_candidate_title: str,
    image_paths_written: list[str],
    database_ids_written: dict[str, str],
    file_entries: list[dict[str, Any]],
    job_id: str | None = None,
    canonical_entity_ids: dict[str, str] | None = None,
) -> dict[str, Any]:
    return {
        "job_status": "succeeded",
        "job_id": job_id,
        "processed_at": _timestamp(),
        "library_name": library_name,
        "library_category": library_category,
        "media_shape": media_shape,
        "resolved_title": resolved_title,
        "provider_name": provider_name,
        "provider_id": provider_id,
        "original_folder_path": str(folder_path),
        "extracted_candidate_title": extracted_candidate_title,
        "image_paths_written": image_paths_written,
        "database_ids_written": database_ids_written,
        "canonical_entity_ids": canonical_entity_ids or {},
        "files": file_entries,
    }


def write_marker_file(folder_path: Path, marker_name: str, payload: dict[str, Any]) -> Path:
    marker_path = folder_path / marker_name
    marker_path.write_text(yaml.safe_dump(payload, sort_keys=False), encoding="utf-8")
    return marker_path
