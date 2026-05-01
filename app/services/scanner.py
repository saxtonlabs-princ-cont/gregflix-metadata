from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from app.config import AppConfig, LibraryConfig
from app.services.marker_files import MarkerState, detect_marker_state


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


class LibraryScanner:
    def __init__(self, config: AppConfig) -> None:
        self.config = config

    def marker_state(self, folder_path: Path) -> MarkerState:
        return detect_marker_state(
            folder_path,
            self.config.scanner.success_marker,
            self.config.scanner.failure_marker,
        )

    def should_include_file(self, path: Path) -> bool:
        return path.is_file() and path.suffix.lower() in self.config.scanner.supported_extensions

    def scan_library(self, library: LibraryConfig) -> ScanSummary:
        queued: list[ScanCandidate] = []
        skipped_success = 0
        skipped_failure = 0
        skipped_invalid = 0

        if not library.path.exists():
            logger.warning("library root does not exist", extra={"event": "root_scanned", "folder_path": str(library.path)})
            return ScanSummary(queued=queued, skipped_success=0, skipped_failure=0, skipped_invalid=0)

        for child in sorted(library.path.iterdir()):
            if not child.is_dir():
                continue
            state = self.marker_state(child)
            if state.is_invalid:
                skipped_invalid += 1
                logger.error(
                    "folder skipped due to dual markers",
                    extra={"event": "folder_skipped_dual_markers", "folder_path": str(child), "library_name": library.name},
                )
                continue
            if state.success_exists:
                skipped_success += 1
                logger.info(
                    "folder skipped due to success marker",
                    extra={"event": "folder_skipped_success", "folder_path": str(child), "library_name": library.name},
                )
                continue
            if state.failure_exists:
                skipped_failure += 1
                logger.info(
                    "folder skipped due to failure marker",
                    extra={"event": "folder_skipped_failure", "folder_path": str(child), "library_name": library.name},
                )
                continue

            queued.append(
                ScanCandidate(
                    library_name=library.name,
                    library_category=library.category,
                    folder_path=child.resolve(),
                )
            )
            logger.info(
                "folder queued",
                extra={"event": "folder_queued", "folder_path": str(child), "library_name": library.name},
            )

        return ScanSummary(
            queued=queued,
            skipped_success=skipped_success,
            skipped_failure=skipped_failure,
            skipped_invalid=skipped_invalid,
        )

    def scan_all(self) -> ScanSummary:
        all_queued: list[ScanCandidate] = []
        skipped_success = 0
        skipped_failure = 0
        skipped_invalid = 0
        for library in self.config.enabled_libraries:
            logger.info("root scanned", extra={"event": "root_scanned", "folder_path": str(library.path), "library_name": library.name})
            summary = self.scan_library(library)
            all_queued.extend(summary.queued)
            skipped_success += summary.skipped_success
            skipped_failure += summary.skipped_failure
            skipped_invalid += summary.skipped_invalid
        return ScanSummary(
            queued=all_queued,
            skipped_success=skipped_success,
            skipped_failure=skipped_failure,
            skipped_invalid=skipped_invalid,
        )
