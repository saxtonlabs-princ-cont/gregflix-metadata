from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig
from app.models import MediaFile, MediaImage, MediaItem, MetadataJob
from app.services.filename_parser import (
    ParsedVideoFile,
    build_episode_sanitized_name,
    build_film_sanitized_name,
    parse_movie_candidate,
    parse_season_folder_name,
    parse_video_filename,
)
from app.services.image_store import ImageStore
from app.services.marker_files import build_failure_marker_content, build_success_marker_content, write_marker_file
from app.services.provider import ProviderDetails
from app.services.tmdb_client import TmdbClient


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestRequest:
    folder_path: Path
    library_name: str
    library_category: str
    job_id: str


class MetadataIngester:
    def __init__(self, config: AppConfig, session_factory: sessionmaker, tmdb_client: TmdbClient, image_store: ImageStore) -> None:
        self.config = config
        self.session_factory = session_factory
        self.tmdb_client = tmdb_client
        self.image_store = image_store

    async def ingest(self, request: IngestRequest) -> None:
        logger.info("job started", extra={"event": "job_started", "folder_path": str(request.folder_path), "job_id": request.job_id})
        raw_filenames = [path.name for path in request.folder_path.rglob("*") if path.is_file()]
        candidate_title: str | None = None
        provider_result_count: int | None = None
        try:
            parsed_files = self._collect_video_files(request.folder_path)
            if not parsed_files:
                raise ValueError("No supported video files found")

            candidate_title = self._candidate_title(request.folder_path, parsed_files)
            logger.info("parser result", extra={"event": "parser_result", "folder_path": str(request.folder_path)})
            logger.info("provider lookup started", extra={"event": "provider_lookup_started", "folder_path": str(request.folder_path)})
            search_results = await self._search_provider(candidate_title, parsed_files)
            provider_result_count = len(search_results)
            logger.info(
                "provider lookup result count",
                extra={"event": "provider_lookup_result_count", "folder_path": str(request.folder_path), "count": provider_result_count},
            )
            if not search_results:
                raise LookupError(f"No provider results found for candidate title: {candidate_title}")

            selected = search_results[0]
            details = await self._fetch_details(selected.provider_id, selected.media_shape)
            logger.info("provider details fetched", extra={"event": "provider_details_fetched", "folder_path": str(request.folder_path)})
            image_paths = await self._download_images(details, parsed_files)
            database_ids = self._upsert_database(request, details, parsed_files, image_paths)
            logger.info("database upsert completed", extra={"event": "database_upsert_completed", "folder_path": str(request.folder_path)})
            success_payload = build_success_marker_content(
                library_name=request.library_name,
                library_category=request.library_category,
                folder_path=request.folder_path,
                media_shape=details.media_shape,
                resolved_title=details.title,
                provider_name=details.provider_name,
                provider_id=details.provider_id,
                extracted_candidate_title=candidate_title,
                image_paths_written=image_paths,
                database_ids_written=database_ids,
                file_entries=self._build_success_file_entries(parsed_files, details),
            )
            write_marker_file(request.folder_path, self.config.scanner.success_marker, success_payload)
            logger.info("success marker written", extra={"event": "success_marker_written", "folder_path": str(request.folder_path)})
            self._update_job_status(request.job_id, "succeeded", details.media_shape, None)
        except Exception as exc:
            failure_payload = build_failure_marker_content(
                library_name=request.library_name,
                library_category=request.library_category,
                folder_path=request.folder_path,
                raw_folder_name=request.folder_path.name,
                raw_filenames=raw_filenames,
                extracted_candidate_title=candidate_title,
                failure_stage="ingest",
                failure_reason=str(exc),
                exception=exc,
                provider_response_count=provider_result_count,
            )
            write_marker_file(request.folder_path, self.config.scanner.failure_marker, failure_payload)
            logger.error(
                "failure marker written",
                exc_info=exc,
                extra={"event": "failure_marker_written", "folder_path": str(request.folder_path), "stage": "ingest"},
            )
            self._update_job_status(request.job_id, "failed", None, str(exc))

    def _collect_video_files(self, folder_path: Path) -> list[ParsedVideoFile]:
        parsed: list[ParsedVideoFile] = []
        for path in sorted(folder_path.rglob("*")):
            if path.is_file() and path.suffix.lower() in self.config.scanner.supported_extensions:
                parsed_file = parse_video_filename(path)
                season_folder = path.parent if path.parent != folder_path else None
                if parsed_file.season_number is None and season_folder is not None:
                    season_number = parse_season_folder_name(season_folder.name)
                    if season_number is not None:
                        parsed_file = ParsedVideoFile(
                            path=parsed_file.path,
                            original_filename=parsed_file.original_filename,
                            extension=parsed_file.extension,
                            candidate_title=parsed_file.candidate_title,
                            season_number=season_number,
                            episode_number=parsed_file.episode_number,
                            episode_title=parsed_file.episode_title,
                        )
                parsed.append(parsed_file)
        return parsed

    def _candidate_title(self, folder_path: Path, parsed_files: list[ParsedVideoFile]) -> str:
        folder_title, _ = parse_movie_candidate(folder_path.name)
        if folder_title:
            return folder_title
        return parsed_files[0].candidate_title

    async def _search_provider(self, candidate_title: str, parsed_files: list[ParsedVideoFile]):
        is_series_candidate = any(item.season_number is not None and item.episode_number is not None for item in parsed_files)
        if is_series_candidate:
            tv_results = await self.tmdb_client.search_tv(candidate_title)
            movie_results = await self.tmdb_client.search_movie(candidate_title)
            return tv_results + movie_results
        movie_results = await self.tmdb_client.search_movie(candidate_title)
        tv_results = await self.tmdb_client.search_tv(candidate_title)
        return movie_results + tv_results

    async def _fetch_details(self, provider_id: str, media_shape: str) -> ProviderDetails:
        if media_shape == "series":
            return await self.tmdb_client.get_tv_details(provider_id)
        return await self.tmdb_client.get_movie_details(provider_id)

    async def _download_images(self, details: ProviderDetails, parsed_files: list[ParsedVideoFile]) -> list[str]:
        written_paths: list[str] = []

        async def maybe_download(relative_path: str | None, target_path: Path) -> None:
            image_url = self.tmdb_client.image_url(relative_path)
            if not image_url:
                return
            logger.info("image download started", extra={"event": "image_download_started", "folder_path": str(target_path)})
            content = await self.tmdb_client.download_image(image_url)
            final_path = self.image_store.write_bytes(target_path, content)
            written_paths.append(str(final_path))
            logger.info("image download completed", extra={"event": "image_download_completed", "folder_path": str(final_path)})

        if details.media_shape == "film":
            await maybe_download(details.poster_path, self.image_store.movie_image_path(details.provider_name, details.provider_id, "poster"))
            await maybe_download(details.backdrop_path, self.image_store.movie_image_path(details.provider_name, details.provider_id, "backdrop"))
        else:
            await maybe_download(details.poster_path, self.image_store.tv_image_path(details.provider_name, details.provider_id, "poster"))
            await maybe_download(details.backdrop_path, self.image_store.tv_image_path(details.provider_name, details.provider_id, "backdrop"))
            for season in details.seasons:
                await maybe_download(
                    season.poster_path,
                    self.image_store.season_image_path(details.provider_name, details.provider_id, season.season_number),
                )
                for episode in season.episodes:
                    parsed_match = next(
                        (
                            item
                            for item in parsed_files
                            if item.season_number == episode.season_number and item.episode_number == episode.episode_number
                        ),
                        None,
                    )
                    if parsed_match is None:
                        continue
                    await maybe_download(
                        episode.still_path,
                        self.image_store.episode_still_path(
                            details.provider_name,
                            details.provider_id,
                            episode.season_number,
                            episode.episode_number,
                        ),
                    )
        return written_paths

    def _upsert_database(self, request: IngestRequest, details: ProviderDetails, parsed_files: list[ParsedVideoFile], image_paths: list[str]) -> dict[str, str]:
        with self.session_factory() as session:
            item = self._get_or_create_media_item(session, request.library_category, details)
            self._upsert_media_files(session, item, parsed_files, details)
            self._upsert_media_images(session, item, details, image_paths)
            session.commit()
            return {"media_item_id": str(item.id)}

    def _get_or_create_media_item(self, session: Session, library_category: str, details: ProviderDetails) -> MediaItem:
        existing = session.scalar(
            select(MediaItem).where(
                MediaItem.external_provider == details.provider_name,
                MediaItem.external_provider_id == details.provider_id,
                MediaItem.media_shape == details.media_shape,
            )
        )
        if existing is None:
            existing = MediaItem(
                media_shape=details.media_shape,
                library_category=library_category,
                title=details.title,
                sort_title=details.sort_title,
                original_title=details.original_title,
                overview=details.overview,
                release_date=details.release_date,
                release_year=details.release_year,
                runtime_minutes=details.runtime_minutes,
                external_provider=details.provider_name,
                external_provider_id=details.provider_id,
                external_imdb_id=details.external_imdb_id,
                metadata_fetched=True,
                metadata_fetched_at=datetime.now(timezone.utc),
            )
            session.add(existing)
            session.flush()
            return existing

        existing.library_category = library_category
        existing.title = details.title
        existing.sort_title = details.sort_title
        existing.original_title = details.original_title
        existing.overview = details.overview
        existing.release_date = details.release_date
        existing.release_year = details.release_year
        existing.runtime_minutes = details.runtime_minutes
        existing.external_imdb_id = details.external_imdb_id
        existing.metadata_fetched = True
        existing.metadata_fetched_at = datetime.now(timezone.utc)
        session.add(existing)
        session.flush()
        return existing

    def _upsert_media_files(self, session: Session, media_item: MediaItem, parsed_files: list[ParsedVideoFile], details: ProviderDetails) -> None:
        episode_titles = {
            (episode.season_number, episode.episode_number): episode.title
            for season in details.seasons
            for episode in season.episodes
        }
        for parsed_file in parsed_files:
            existing = session.scalar(select(MediaFile).where(MediaFile.original_path == str(parsed_file.path.resolve())))
            if details.media_shape == "series" and parsed_file.season_number and parsed_file.episode_number:
                episode_title = episode_titles.get((parsed_file.season_number, parsed_file.episode_number)) or parsed_file.episode_title
                sanitized_name = build_episode_sanitized_name(
                    details.title,
                    parsed_file.season_number,
                    parsed_file.episode_number,
                    episode_title,
                    parsed_file.extension,
                )
            else:
                sanitized_name = build_film_sanitized_name(details.title, details.release_year, parsed_file.extension)

            if existing is None:
                existing = MediaFile(
                    media_item_id=media_item.id,
                    original_path=str(parsed_file.path.resolve()),
                    original_filename=parsed_file.original_filename,
                    sanitized_name=sanitized_name,
                    extension=parsed_file.extension,
                    size_bytes=parsed_file.path.stat().st_size if parsed_file.path.exists() else None,
                    season_number=parsed_file.season_number,
                    episode_number=parsed_file.episode_number,
                )
            else:
                existing.media_item_id = media_item.id
                existing.original_filename = parsed_file.original_filename
                existing.sanitized_name = sanitized_name
                existing.extension = parsed_file.extension
                existing.size_bytes = parsed_file.path.stat().st_size if parsed_file.path.exists() else None
                existing.season_number = parsed_file.season_number
                existing.episode_number = parsed_file.episode_number
            session.add(existing)

    def _upsert_media_images(self, session: Session, media_item: MediaItem, details: ProviderDetails, image_paths: list[str]) -> None:
        for image_path in image_paths:
            existing = session.scalar(select(MediaImage).where(MediaImage.absolute_path == image_path))
            image_type = Path(image_path).stem
            if existing is None:
                existing = MediaImage(
                    media_item_id=media_item.id,
                    image_type=image_type,
                    absolute_path=image_path,
                    source_provider=details.provider_name,
                    source_provider_id=details.provider_id,
                )
            else:
                existing.media_item_id = media_item.id
                existing.image_type = image_type
                existing.source_provider = details.provider_name
                existing.source_provider_id = details.provider_id
            session.add(existing)

    def _build_success_file_entries(self, parsed_files: list[ParsedVideoFile], details: ProviderDetails) -> list[dict[str, str | int | None]]:
        episode_titles = {
            (episode.season_number, episode.episode_number): episode.title
            for season in details.seasons
            for episode in season.episodes
        }
        entries = []
        for parsed_file in parsed_files:
            if details.media_shape == "series" and parsed_file.season_number and parsed_file.episode_number:
                episode_title = episode_titles.get((parsed_file.season_number, parsed_file.episode_number)) or parsed_file.episode_title
                sanitized_name = build_episode_sanitized_name(
                    details.title,
                    parsed_file.season_number,
                    parsed_file.episode_number,
                    episode_title,
                    parsed_file.extension,
                )
            else:
                sanitized_name = build_film_sanitized_name(details.title, details.release_year, parsed_file.extension)
                episode_title = None
            entries.append(
                {
                    "original_path": str(parsed_file.path.resolve()),
                    "original_filename": parsed_file.original_filename,
                    "sanitized_name": sanitized_name,
                    "season_number": parsed_file.season_number,
                    "episode_number": parsed_file.episode_number,
                    "episode_title": episode_title,
                }
            )
        return entries

    def _update_job_status(self, job_id: str, status: str, media_shape: str | None, error: str | None) -> None:
        with self.session_factory() as session:
            job = session.get(MetadataJob, uuid.UUID(job_id))
            if job is None:
                return
            job.status = status
            job.media_shape = media_shape
            job.finished_at = datetime.now(timezone.utc)
            job.error = error
            session.add(job)
            session.commit()
