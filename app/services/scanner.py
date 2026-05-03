from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig, LibraryConfig
from app.models import CanonicalMediaFile, MediaEntity, MediaFile, MetadataIssue, MetadataJob
from app.services.marker_files import MarkerState, detect_marker_state, read_marker_file


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ScanCandidate:
    library_name: str
    library_category: str
    folder_path: Path


@dataclass(frozen=True)
class ScanSummary:
    queued: list[ScanCandidate]
    skipped_success: int
    skipped_failure: int
    skipped_invalid: int
    reconciled_existing: int = 0
    issues_created: int = 0


class LibraryScanner:
    def __init__(self, config: AppConfig, session_factory: sessionmaker | None = None) -> None:
        self.config = config
        self.session_factory = session_factory

    def marker_state(self, folder_path: Path) -> MarkerState:
        return detect_marker_state(
            folder_path,
            self.config.scanner.success_marker,
            self.config.scanner.failure_marker,
        )

    def should_include_file(self, path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in self.config.scanner.supported_extensions

    def scan_library(self, library: LibraryConfig, *, retry_failed: bool = False, reprocess: bool = False) -> ScanSummary:
        queued: list[ScanCandidate] = []
        skipped_success = 0
        skipped_failure = 0
        skipped_invalid = 0
        reconciled_existing = 0
        issues_created = 0

        if not library.path.exists():
            logger.warning("library root does not exist", extra={"event": "root_scanned", "folder_path": str(library.path)})
            return ScanSummary(queued=queued, skipped_success=0, skipped_failure=0, skipped_invalid=0)

        for child in sorted(library.path.iterdir()):
            if not child.is_dir():
                continue
            child_summary = self._scan_child(library, child.resolve(), retry_failed=retry_failed, reprocess=reprocess)
            queued.extend(child_summary.queued)
            skipped_success += child_summary.skipped_success
            skipped_failure += child_summary.skipped_failure
            skipped_invalid += child_summary.skipped_invalid
            reconciled_existing += child_summary.reconciled_existing
            issues_created += child_summary.issues_created

        return ScanSummary(
            queued=queued,
            skipped_success=skipped_success,
            skipped_failure=skipped_failure,
            skipped_invalid=skipped_invalid,
            reconciled_existing=reconciled_existing,
            issues_created=issues_created,
        )

    def scan_all(self, *, retry_failed: bool = False, reprocess: bool = False, folder_path: Path | None = None) -> ScanSummary:
        all_queued: list[ScanCandidate] = []
        skipped_success = 0
        skipped_failure = 0
        skipped_invalid = 0
        reconciled_existing = 0
        issues_created = 0
        for library in self.config.enabled_libraries:
            logger.info("root scanned", extra={"event": "root_scanned", "folder_path": str(library.path), "library_name": library.name})
            if folder_path is not None:
                if not _is_relative_to(folder_path.resolve(), library.path.resolve()):
                    continue
                summary = self.scan_folder(library, folder_path.resolve(), retry_failed=retry_failed, reprocess=reprocess)
            else:
                summary = self.scan_library(library, retry_failed=retry_failed, reprocess=reprocess)
            all_queued.extend(summary.queued)
            skipped_success += summary.skipped_success
            skipped_failure += summary.skipped_failure
            skipped_invalid += summary.skipped_invalid
            reconciled_existing += summary.reconciled_existing
            issues_created += summary.issues_created
        return ScanSummary(
            queued=all_queued,
            skipped_success=skipped_success,
            skipped_failure=skipped_failure,
            skipped_invalid=skipped_invalid,
            reconciled_existing=reconciled_existing,
            issues_created=issues_created,
        )

    def scan_folder(
        self,
        library: LibraryConfig,
        folder_path: Path,
        *,
        retry_failed: bool = False,
        reprocess: bool = False,
    ) -> ScanSummary:
        if not folder_path.exists() or not folder_path.is_dir():
            return ScanSummary(queued=[], skipped_success=0, skipped_failure=0, skipped_invalid=0)
        return self._scan_child(library, folder_path, retry_failed=retry_failed, reprocess=reprocess)

    def _scan_child(
        self,
        library: LibraryConfig,
        folder_path: Path,
        *,
        retry_failed: bool,
        reprocess: bool,
    ) -> ScanSummary:
        queued: list[ScanCandidate] = []
        skipped_success = 0
        skipped_failure = 0
        skipped_invalid = 0
        reconciled_existing = 0
        issues_created = 0
        state = self.marker_state(folder_path)
        if state.is_invalid:
            skipped_invalid += 1
            if self._upsert_metadata_issue(
                folder_path,
                "invalid_marker_state",
                "warning",
                "Folder has both success and failure markers",
                "Both marker files exist. Postgres is authoritative; marker state must be repaired.",
                {"success_marker": self.config.scanner.success_marker, "failure_marker": self.config.scanner.failure_marker},
            ):
                issues_created += 1
            logger.error(
                "folder skipped due to dual markers",
                extra={"event": "folder_skipped_dual_markers", "folder_path": str(folder_path), "library_name": library.name},
            )
            if reprocess or retry_failed:
                queued.append(self._candidate(library, folder_path))
            return ScanSummary(queued, skipped_success, skipped_failure, skipped_invalid, reconciled_existing, issues_created)
        if state.success_exists:
            if not reprocess and self._success_marker_is_current(folder_path):
                skipped_success += 1
                logger.info(
                    "folder skipped due to current success marker",
                    extra={"event": "folder_skipped_success", "folder_path": str(folder_path), "library_name": library.name},
                )
                return ScanSummary(queued, skipped_success, skipped_failure, skipped_invalid, reconciled_existing, issues_created)
            if self._upsert_metadata_issue(
                folder_path,
                "success_marker_db_mismatch",
                "warning",
                "Success marker does not match current database state",
                "Success marker exists, but referenced Postgres records are missing or inconsistent.",
                read_marker_file(folder_path, self.config.scanner.success_marker),
            ):
                issues_created += 1
            queued.append(self._candidate(library, folder_path))
            return ScanSummary(queued, skipped_success, skipped_failure, skipped_invalid, reconciled_existing, issues_created)
        if state.failure_exists:
            if not retry_failed and self._has_open_failure_issue(folder_path):
                skipped_failure += 1
                logger.info(
                    "folder skipped due to open failure issue",
                    extra={"event": "folder_skipped_failure", "folder_path": str(folder_path), "library_name": library.name},
                )
                return ScanSummary(queued, skipped_success, skipped_failure, skipped_invalid, reconciled_existing, issues_created)
            queued.append(self._candidate(library, folder_path))
            return ScanSummary(queued, skipped_success, skipped_failure, skipped_invalid, reconciled_existing, issues_created)

        if not reprocess and self._postgres_knows_folder(folder_path):
            reconciled_existing += 1
            logger.info(
                "folder reconciled from database state",
                extra={"event": "folder_reconciled_database_state", "folder_path": str(folder_path), "library_name": library.name},
            )
            return ScanSummary(queued, skipped_success, skipped_failure, skipped_invalid, reconciled_existing, issues_created)

        queued.append(self._candidate(library, folder_path))
        logger.info(
            "folder queued",
            extra={"event": "folder_queued", "folder_path": str(folder_path), "library_name": library.name},
        )
        return ScanSummary(queued, skipped_success, skipped_failure, skipped_invalid, reconciled_existing, issues_created)

    def _candidate(self, library: LibraryConfig, folder_path: Path) -> ScanCandidate:
        return ScanCandidate(library_name=library.name, library_category=library.category, folder_path=folder_path)

    def _success_marker_is_current(self, folder_path: Path) -> bool:
        marker = read_marker_file(folder_path, self.config.scanner.success_marker)
        if not marker or self.session_factory is None:
            return False
        job_id = marker.get("job_id")
        canonical_entity_ids = marker.get("canonical_entity_ids") or {}
        database_ids = marker.get("database_ids_written") or {}
        entity_id = canonical_entity_ids.get("root") or canonical_entity_ids.get("media_entity_id") or database_ids.get("media_entity_id")
        media_item_id = database_ids.get("media_item_id")
        with self.session_factory() as session:
            if job_id:
                parsed_job_id = _uuid_or_none(job_id)
                if parsed_job_id is None or session.get(MetadataJob, parsed_job_id) is None:
                    return False
            parsed_entity_id = _uuid_or_none(entity_id)
            if entity_id and parsed_entity_id is None:
                return False
            if parsed_entity_id is not None and session.get(MediaEntity, parsed_entity_id) is not None:
                return True
            if media_item_id and self._folder_has_legacy_file(session, folder_path, _uuid_or_none(media_item_id)):
                return True
        return False

    def _has_open_failure_issue(self, folder_path: Path) -> bool:
        if self.session_factory is None:
            return True
        marker = read_marker_file(folder_path, self.config.scanner.failure_marker)
        issue_id = _uuid_or_none(marker.get("metadata_issue_id"))
        with self.session_factory() as session:
            if issue_id is not None:
                issue = session.get(MetadataIssue, issue_id)
                return issue is not None and issue.status == "open"
            return (
                session.scalar(
                    select(MetadataIssue).where(
                        MetadataIssue.folder_path == str(folder_path),
                        MetadataIssue.status == "open",
                    )
                )
                is not None
            )

    def _postgres_knows_folder(self, folder_path: Path) -> bool:
        if self.session_factory is None:
            return False
        with self.session_factory() as session:
            prefix = _path_prefix(folder_path)
            known_file = session.scalar(select(CanonicalMediaFile.id).where(CanonicalMediaFile.original_path.like(prefix)).limit(1))
            if known_file is None:
                known_file = session.scalar(select(MediaFile.id).where(MediaFile.original_path.like(prefix)).limit(1))
            known_job = session.scalar(select(MetadataJob.id).where(MetadataJob.folder_path == str(folder_path)).limit(1))
            return known_file is not None or known_job is not None

    def _folder_has_legacy_file(self, session: Session, folder_path: Path, media_item_id: uuid.UUID | None) -> bool:
        if media_item_id is None:
            return False
        return (
            session.scalar(
                select(MediaFile.id)
                .where(MediaFile.media_item_id == media_item_id, MediaFile.original_path.like(_path_prefix(folder_path)))
                .limit(1)
            )
            is not None
        )

    def _upsert_metadata_issue(
        self,
        folder_path: Path,
        issue_type: str,
        severity: str,
        title: str,
        detail: str,
        payload: dict[str, object],
    ) -> bool:
        if self.session_factory is None:
            return False
        with self.session_factory() as session:
            issue = session.scalar(
                select(MetadataIssue).where(
                    MetadataIssue.folder_path == str(folder_path),
                    MetadataIssue.issue_type == issue_type,
                    MetadataIssue.status == "open",
                )
            )
            created = issue is None
            if issue is None:
                issue = MetadataIssue(issue_type=issue_type, severity=severity, status="open", title=title, folder_path=str(folder_path))
            issue.severity = severity
            issue.title = title
            issue.detail = detail
            issue.payload = payload
            session.add(issue)
            session.commit()
            return created


def _uuid_or_none(value: object) -> uuid.UUID | None:
    if not value:
        return None
    try:
        return uuid.UUID(str(value))
    except ValueError:
        return None


def _path_prefix(folder_path: Path) -> str:
    return f"{folder_path.resolve()}{os.sep}%"


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False
