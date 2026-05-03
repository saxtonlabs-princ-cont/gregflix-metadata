from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app.config import AppConfig
from app.models import (
    ArtworkAsset,
    CanonicalMediaFile,
    EntityAlias,
    MediaEntity,
    MediaFile,
    MediaImage,
    MediaItem,
    MetadataEvidence,
    MetadataIssue,
    MetadataJob,
    ProviderMatchCandidate,
    ProviderIdentity,
)
from app.services.filename_parser import (
    ParsedVideoFile,
    build_episode_sanitized_name,
    build_film_sanitized_name,
    parse_movie_candidate,
    parse_season_folder_name,
    parse_video_filename,
)
from app.services.image_store import ImageStore
from app.services.local_assets import LocalAssetDiscovery, LocalArtwork, discover_local_assets
from app.services.marker_files import build_failure_marker_content, build_success_marker_content, write_marker_file
from app.services.provider import ProviderDetails
from app.services.provider_matching import (
    ScoredProviderCandidate,
    build_match_context,
    score_candidates,
    select_best_candidate,
)
from app.services.search_repository import refresh_search_documents
from app.services.tmdb_client import TmdbClient


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestRequest:
    folder_path: Path
    library_name: str
    library_category: str
    job_id: str


class ProviderMatchSelectionError(RuntimeError):
    def __init__(self, message: str, issue_id: str, issue_type: str) -> None:
        super().__init__(message)
        self.issue_id = issue_id
        self.issue_type = issue_type


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

            local_assets = discover_local_assets(request.folder_path)
            candidate_title, candidate_year = self._candidate_title_and_year(request.folder_path, parsed_files)
            logger.info("parser result", extra={"event": "parser_result", "folder_path": str(request.folder_path)})
            logger.info("provider lookup started", extra={"event": "provider_lookup_started", "folder_path": str(request.folder_path)})
            search_results = await self._search_provider(candidate_title, parsed_files)
            provider_result_count = len(search_results)
            logger.info(
                "provider lookup result count",
                extra={"event": "provider_lookup_result_count", "folder_path": str(request.folder_path), "count": provider_result_count},
            )
            scored_candidates = score_candidates(
                search_results,
                build_match_context(
                    candidate_title=candidate_title,
                    candidate_year=candidate_year,
                    library_category=request.library_category,
                    parsed_files=parsed_files,
                ),
            )
            selection = select_best_candidate(
                scored_candidates,
                confidence_threshold=self.config.matching.confidence_threshold,
                ambiguity_delta=self.config.matching.ambiguity_delta,
            )
            self._upsert_provider_match_candidates(request, selection.candidates, selection.selected)
            if selection.selected is None:
                issue_id = self._record_metadata_issue(
                    request,
                    selection.issue_type or "provider_match_unresolved",
                    "warning",
                    "Provider match requires manual resolution",
                    selection.issue_detail or "No provider candidate was selected",
                    {
                        "candidate_title": candidate_title,
                        "candidate_year": candidate_year,
                        "confidence_threshold": self.config.matching.confidence_threshold,
                        "ambiguity_delta": self.config.matching.ambiguity_delta,
                        "candidates": [_candidate_issue_payload(candidate) for candidate in selection.candidates],
                    },
                )
                raise ProviderMatchSelectionError(
                    selection.issue_detail or "Provider match unresolved",
                    issue_id,
                    selection.issue_type or "provider_match_unresolved",
                )

            selected = selection.selected.result
            details = await self._fetch_details(selected.provider_id, selected.media_shape)
            logger.info("provider details fetched", extra={"event": "provider_details_fetched", "folder_path": str(request.folder_path)})
            image_paths = []
            if self.config.artwork.preference != "local_only":
                image_paths = await self._download_images(details, parsed_files)
            local_artwork_paths = self._copy_local_artwork(details, local_assets.artwork)
            database_ids = self._upsert_database(
                request,
                details,
                parsed_files,
                image_paths,
                local_artwork_paths,
                local_assets,
                candidate_title,
                provider_result_count,
            )
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
                job_id=request.job_id,
                canonical_entity_ids={"root": database_ids["media_entity_id"]} if "media_entity_id" in database_ids else {},
                file_entries=self._build_success_file_entries(parsed_files, details),
            )
            self._remove_marker_if_exists(request.folder_path, self.config.scanner.failure_marker)
            write_marker_file(request.folder_path, self.config.scanner.success_marker, success_payload)
            logger.info("success marker written", extra={"event": "success_marker_written", "folder_path": str(request.folder_path)})
            self._update_job_status(request.job_id, "succeeded", details.media_shape, None)
        except Exception as exc:
            if isinstance(exc, ProviderMatchSelectionError):
                metadata_issue_id = exc.issue_id
                failure_stage = "provider_match"
                failure_reason = str(exc)
            else:
                metadata_issue_id = self._record_metadata_issue(
                    request,
                    "ingestion_failed",
                    "error",
                    "Metadata ingestion failed",
                    str(exc),
                    {
                        "raw_folder_name": request.folder_path.name,
                        "raw_filenames_considered": raw_filenames,
                        "extracted_candidate_title": candidate_title,
                        "provider_response_count": provider_result_count,
                        "exception_type": exc.__class__.__name__,
                        "exception_message": str(exc),
                    },
                )
                failure_stage = "ingest"
                failure_reason = str(exc)
            failure_payload = build_failure_marker_content(
                library_name=request.library_name,
                library_category=request.library_category,
                folder_path=request.folder_path,
                raw_folder_name=request.folder_path.name,
                raw_filenames=raw_filenames,
                extracted_candidate_title=candidate_title,
                failure_stage=failure_stage,
                failure_reason=failure_reason,
                exception=exc,
                provider_response_count=provider_result_count,
                job_id=request.job_id,
                metadata_issue_id=metadata_issue_id,
            )
            self._remove_marker_if_exists(request.folder_path, self.config.scanner.success_marker)
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

    def _candidate_title_and_year(self, folder_path: Path, parsed_files: list[ParsedVideoFile]) -> tuple[str, int | None]:
        folder_title, folder_year = parse_movie_candidate(folder_path.name)
        if folder_title:
            return folder_title, folder_year
        return parsed_files[0].candidate_title, None

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

    def _upsert_database(
        self,
        request: IngestRequest,
        details: ProviderDetails,
        parsed_files: list[ParsedVideoFile],
        image_paths: list[str],
        local_artwork_paths: list[tuple[LocalArtwork, str]],
        local_assets: LocalAssetDiscovery,
        candidate_title: str,
        provider_result_count: int,
    ) -> dict[str, str]:
        with self.session_factory() as session:
            item = self._get_or_create_media_item(session, request.library_category, details)
            self._upsert_media_files(session, item, parsed_files, details)
            self._upsert_media_images(session, item, details, image_paths)
            entities = self._upsert_canonical_entities(session, request.library_category, details)
            root_entity = entities[("root", None, None)]
            self._upsert_provider_identity(session, root_entity, details.provider_name, details.media_shape, details.provider_id, True)
            self._upsert_entity_aliases(session, root_entity, details, candidate_title)
            self._upsert_canonical_media_files(session, entities, parsed_files, details)
            self._upsert_artwork_assets(session, entities, details, image_paths)
            self._upsert_local_artwork_assets(session, entities, details, local_artwork_paths)
            self._add_metadata_evidence(
                session,
                request,
                root_entity,
                details,
                parsed_files,
                local_assets,
                candidate_title,
                provider_result_count,
            )
            refresh_search_documents(session, [entity.id for entity in entities.values()])
            session.commit()
            return {"media_item_id": str(item.id), "media_entity_id": str(root_entity.id)}

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

    def _upsert_canonical_entities(
        self,
        session: Session,
        library_category: str,
        details: ProviderDetails,
    ) -> dict[tuple[str, int | None, int | None], MediaEntity]:
        root_type = "series" if details.media_shape == "series" else "movie"
        root = self._get_or_create_root_entity(session, library_category, details, root_type)
        entities: dict[tuple[str, int | None, int | None], MediaEntity] = {("root", None, None): root}

        if root_type != "series":
            return entities

        for season in details.seasons:
            season_title = f"{details.title} - Season {season.season_number:02d}"
            season_entity = self._get_or_create_child_entity(
                session,
                parent=root,
                entity_type="season",
                title=season_title,
                sort_title=season_title,
                season_number=season.season_number,
                episode_number=None,
                library_category=library_category,
            )
            self._upsert_provider_identity(
                session,
                season_entity,
                details.provider_name,
                "season",
                f"{details.provider_id}:season:{season.season_number}",
                False,
            )
            entities[("season", season.season_number, None)] = season_entity
            for episode in season.episodes:
                episode_title = episode.title or f"Episode {episode.episode_number}"
                episode_entity = self._get_or_create_child_entity(
                    session,
                    parent=season_entity,
                    entity_type="episode",
                    title=episode_title,
                    sort_title=episode_title,
                    season_number=episode.season_number,
                    episode_number=episode.episode_number,
                    library_category=library_category,
                )
                self._upsert_provider_identity(
                    session,
                    episode_entity,
                    details.provider_name,
                    "episode",
                    f"{details.provider_id}:episode:{episode.season_number}:{episode.episode_number}",
                    False,
                )
                entities[("episode", episode.season_number, episode.episode_number)] = episode_entity
        return entities

    def _get_or_create_root_entity(
        self,
        session: Session,
        library_category: str,
        details: ProviderDetails,
        entity_type: str,
    ) -> MediaEntity:
        provider_media_type = details.media_shape
        identity = session.scalar(
            select(ProviderIdentity).where(
                ProviderIdentity.provider_name == details.provider_name,
                ProviderIdentity.provider_media_type == provider_media_type,
                ProviderIdentity.provider_id == details.provider_id,
            )
        )
        entity = session.get(MediaEntity, identity.entity_id) if identity is not None else None
        if entity is None:
            entity = MediaEntity(entity_type=entity_type, title=details.title, sort_title=details.sort_title)
        entity.entity_type = entity_type
        entity.library_category = library_category
        entity.title = details.title
        entity.sort_title = details.sort_title
        entity.original_title = details.original_title
        entity.overview = details.overview
        entity.release_date = details.release_date
        entity.release_year = details.release_year
        entity.runtime_minutes = details.runtime_minutes
        entity.metadata_fetched = True
        entity.metadata_fetched_at = datetime.now(timezone.utc)
        session.add(entity)
        session.flush()
        return entity

    def _get_or_create_child_entity(
        self,
        session: Session,
        *,
        parent: MediaEntity,
        entity_type: str,
        title: str,
        sort_title: str,
        season_number: int,
        episode_number: int | None,
        library_category: str,
    ) -> MediaEntity:
        query = select(MediaEntity).where(
            MediaEntity.parent_id == parent.id,
            MediaEntity.entity_type == entity_type,
            MediaEntity.season_number == season_number,
        )
        if episode_number is None:
            query = query.where(MediaEntity.episode_number.is_(None))
        else:
            query = query.where(MediaEntity.episode_number == episode_number)
        entity = session.scalar(query)
        if entity is None:
            entity = MediaEntity(
                parent_id=parent.id,
                entity_type=entity_type,
                title=title,
                sort_title=sort_title,
                season_number=season_number,
                episode_number=episode_number,
            )
        entity.library_category = library_category
        entity.title = title
        entity.sort_title = sort_title
        entity.season_number = season_number
        entity.episode_number = episode_number
        entity.metadata_fetched = True
        entity.metadata_fetched_at = datetime.now(timezone.utc)
        session.add(entity)
        session.flush()
        return entity

    def _upsert_provider_identity(
        self,
        session: Session,
        entity: MediaEntity,
        provider_name: str,
        provider_media_type: str,
        provider_id: str,
        primary_identity: bool,
    ) -> ProviderIdentity:
        identity = session.scalar(
            select(ProviderIdentity).where(
                ProviderIdentity.provider_name == provider_name,
                ProviderIdentity.provider_media_type == provider_media_type,
                ProviderIdentity.provider_id == provider_id,
            )
        )
        if identity is None:
            identity = ProviderIdentity(
                provider_name=provider_name,
                provider_media_type=provider_media_type,
                provider_id=provider_id,
            )
        identity.entity_id = entity.id
        identity.primary_identity = primary_identity
        session.add(identity)
        session.flush()
        return identity

    def _upsert_provider_match_candidates(
        self,
        request: IngestRequest,
        candidates: list[ScoredProviderCandidate],
        selected: ScoredProviderCandidate | None,
    ) -> None:
        selected_key = (
            selected.result.provider_name,
            selected.result.media_shape,
            selected.result.provider_id,
        ) if selected is not None else None
        with self.session_factory() as session:
            for candidate in candidates:
                result = candidate.result
                existing = session.scalar(
                    select(ProviderMatchCandidate).where(
                        ProviderMatchCandidate.metadata_job_id == uuid.UUID(request.job_id),
                        ProviderMatchCandidate.provider_name == result.provider_name,
                        ProviderMatchCandidate.provider_media_type == result.media_shape,
                        ProviderMatchCandidate.provider_id == result.provider_id,
                    )
                )
                if existing is None:
                    existing = ProviderMatchCandidate(
                        metadata_job_id=uuid.UUID(request.job_id),
                        provider_name=result.provider_name,
                        provider_media_type=result.media_shape,
                        provider_id=result.provider_id,
                    )
                existing.title = result.title
                existing.original_title = result.original_title
                existing.release_date = result.release_date
                existing.release_year = result.release_year
                existing.popularity = result.popularity
                existing.provider_rank = result.result_rank
                existing.raw_score_components = candidate.raw_score_components
                existing.confidence_score = candidate.confidence_score
                existing.selected = selected_key == (result.provider_name, result.media_shape, result.provider_id)
                session.add(existing)
            session.commit()

    def _upsert_entity_aliases(self, session: Session, entity: MediaEntity, details: ProviderDetails, candidate_title: str) -> None:
        aliases = [(details.title, "provider", True), (candidate_title, "parser", False)]
        if details.original_title and details.original_title != details.title:
            aliases.append((details.original_title, "provider", False))
        for alias, source, is_primary in aliases:
            normalized = _normalize_alias(alias)
            existing = session.scalar(
                select(EntityAlias).where(
                    EntityAlias.entity_id == entity.id,
                    EntityAlias.normalized_alias == normalized,
                    EntityAlias.source == source,
                )
            )
            if existing is None:
                existing = EntityAlias(entity_id=entity.id, alias=alias, normalized_alias=normalized, source=source)
            existing.alias = alias
            existing.is_primary = is_primary
            session.add(existing)

    def _upsert_canonical_media_files(
        self,
        session: Session,
        entities: dict[tuple[str, int | None, int | None], MediaEntity],
        parsed_files: list[ParsedVideoFile],
        details: ProviderDetails,
    ) -> None:
        episode_titles = {
            (episode.season_number, episode.episode_number): episode.title
            for season in details.seasons
            for episode in season.episodes
        }
        root_entity = entities[("root", None, None)]
        for parsed_file in parsed_files:
            playable_entity = root_entity
            if details.media_shape == "series" and parsed_file.season_number and parsed_file.episode_number:
                playable_entity = entities.get(
                    ("episode", parsed_file.season_number, parsed_file.episode_number),
                    root_entity,
                )
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

            original_path = str(parsed_file.path.resolve())
            existing = session.scalar(select(CanonicalMediaFile).where(CanonicalMediaFile.original_path == original_path))
            if existing is None:
                existing = CanonicalMediaFile(original_path=original_path)
            existing.entity_id = playable_entity.id
            existing.original_filename = parsed_file.original_filename
            existing.sanitized_name = sanitized_name
            existing.extension = parsed_file.extension
            existing.size_bytes = parsed_file.path.stat().st_size if parsed_file.path.exists() else None
            existing.season_number = parsed_file.season_number
            existing.episode_number = parsed_file.episode_number
            session.add(existing)

    def _upsert_artwork_assets(
        self,
        session: Session,
        entities: dict[tuple[str, int | None, int | None], MediaEntity],
        details: ProviderDetails,
        image_paths: list[str],
    ) -> None:
        root_entity = entities[("root", None, None)]
        for fallback_rank, image_path in enumerate(image_paths):
            stored_path = str(Path(image_path).resolve())
            entity = self._artwork_entity_for_path(entities, stored_path) or root_entity
            role = Path(stored_path).stem
            existing = session.scalar(select(ArtworkAsset).where(ArtworkAsset.stored_path == stored_path))
            if existing is None:
                existing = ArtworkAsset(stored_path=stored_path)
            existing.entity_id = entity.id
            existing.artwork_role = role
            existing.source = details.provider_name
            existing.source_provider_id = details.provider_id
            existing.original_path = None
            existing.preferred = self.config.artwork.preference in {"prefer_provider", "provider_only"} and (
                fallback_rank == 0 or role in {"poster", "backdrop"}
            )
            existing.fallback_rank = fallback_rank
            session.add(existing)

    def _copy_local_artwork(self, details: ProviderDetails, artwork: list[LocalArtwork]) -> list[tuple[LocalArtwork, str]]:
        if self.config.artwork.preference == "provider_only":
            return []
        written: list[tuple[LocalArtwork, str]] = []
        for local_artwork in artwork:
            target_path = self.image_store.local_artwork_path(
                media_shape=details.media_shape,
                provider_id=details.provider_id,
                source_path=local_artwork.source_path,
                artwork_role=local_artwork.artwork_role,
                season_number=local_artwork.season_number,
                episode_number=local_artwork.episode_number,
            )
            final_path = self.image_store.copy_file(local_artwork.source_path, target_path)
            written.append((local_artwork, str(final_path)))
        return written

    def _upsert_local_artwork_assets(
        self,
        session: Session,
        entities: dict[tuple[str, int | None, int | None], MediaEntity],
        details: ProviderDetails,
        local_artwork_paths: list[tuple[LocalArtwork, str]],
    ) -> None:
        root_entity = entities[("root", None, None)]
        for fallback_rank, (local_artwork, stored_path) in enumerate(local_artwork_paths):
            entity = self._entity_for_local_artwork(entities, local_artwork) or root_entity
            existing = session.scalar(select(ArtworkAsset).where(ArtworkAsset.stored_path == stored_path))
            if existing is None:
                existing = ArtworkAsset(stored_path=stored_path)
            existing.entity_id = entity.id
            existing.artwork_role = local_artwork.artwork_role
            existing.source = "local_file"
            existing.source_provider_id = None
            existing.original_path = str(local_artwork.source_path)
            existing.preferred = self.config.artwork.preference in {"prefer_local", "local_only"}
            existing.fallback_rank = fallback_rank
            session.add(existing)

    def _entity_for_local_artwork(
        self,
        entities: dict[tuple[str, int | None, int | None], MediaEntity],
        local_artwork: LocalArtwork,
    ) -> MediaEntity | None:
        if local_artwork.artwork_role == "season_poster" and local_artwork.season_number is not None:
            return entities.get(("season", local_artwork.season_number, None))
        if (
            local_artwork.artwork_role == "episode_still"
            and local_artwork.season_number is not None
            and local_artwork.episode_number is not None
        ):
            return entities.get(("episode", local_artwork.season_number, local_artwork.episode_number))
        return None

    def _artwork_entity_for_path(
        self,
        entities: dict[tuple[str, int | None, int | None], MediaEntity],
        stored_path: str,
    ) -> MediaEntity | None:
        path = Path(stored_path)
        parts = path.parts
        if "seasons" in parts:
            index = parts.index("seasons")
            if len(parts) > index + 1:
                try:
                    season_number = int(parts[index + 1])
                except ValueError:
                    return None
                return entities.get(("season", season_number, None))
        if "episodes" in parts:
            index = parts.index("episodes")
            if len(parts) > index + 1:
                episode_code = parts[index + 1].upper()
                if len(episode_code) == 6 and episode_code.startswith("S") and "E" in episode_code:
                    try:
                        season_number = int(episode_code[1:3])
                        episode_number = int(episode_code[4:6])
                    except ValueError:
                        return None
                    return entities.get(("episode", season_number, episode_number))
        return None

    def _add_metadata_evidence(
        self,
        session: Session,
        request: IngestRequest,
        entity: MediaEntity,
        details: ProviderDetails,
        parsed_files: list[ParsedVideoFile],
        local_assets: LocalAssetDiscovery,
        candidate_title: str,
        provider_result_count: int,
    ) -> None:
        job_id = uuid.UUID(request.job_id)
        session.add(
            MetadataEvidence(
                entity_id=entity.id,
                metadata_job_id=job_id,
                evidence_type="parser_result",
                source="filename_parser",
                summary=f"Extracted candidate title {candidate_title!r}",
                payload={
                    "folder_path": str(request.folder_path),
                    "candidate_title": candidate_title,
                    "files": [
                        {
                            "original_path": str(parsed.path.resolve()),
                            "candidate_title": parsed.candidate_title,
                            "season_number": parsed.season_number,
                            "episode_number": parsed.episode_number,
                            "episode_title": parsed.episode_title,
                        }
                        for parsed in parsed_files
                    ],
                },
            )
        )
        if local_assets.artwork or local_assets.metadata_files:
            session.add(
                MetadataEvidence(
                    entity_id=entity.id,
                    metadata_job_id=job_id,
                    evidence_type="local_assets",
                    source="local_file",
                    summary=f"Discovered {len(local_assets.artwork)} artwork file(s) and {len(local_assets.metadata_files)} metadata file(s)",
                    payload={
                        "artwork": [
                            {
                                "original_path": str(item.source_path),
                                "artwork_role": item.artwork_role,
                                "season_number": item.season_number,
                                "episode_number": item.episode_number,
                            }
                            for item in local_assets.artwork
                        ],
                        "metadata_files": [
                            {
                                "original_path": str(item.source_path),
                                "metadata_type": item.metadata_type,
                            }
                            for item in local_assets.metadata_files
                        ],
                    },
                )
            )
        session.add(
            MetadataEvidence(
                entity_id=entity.id,
                metadata_job_id=job_id,
                evidence_type="provider_match",
                source=details.provider_name,
                summary=f"Selected {details.provider_name} {details.provider_id} from {provider_result_count} result(s)",
                payload={
                    "provider_name": details.provider_name,
                    "provider_id": details.provider_id,
                    "media_shape": details.media_shape,
                    "title": details.title,
                    "provider_response_count": provider_result_count,
                },
            )
        )

    def _record_metadata_issue(
        self,
        request: IngestRequest,
        issue_type: str,
        severity: str,
        title: str,
        detail: str,
        payload: dict[str, object],
    ) -> str:
        with self.session_factory() as session:
            issue = session.scalar(
                select(MetadataIssue).where(
                    MetadataIssue.folder_path == str(request.folder_path),
                    MetadataIssue.issue_type == issue_type,
                    MetadataIssue.status == "open",
                )
            )
            if issue is None:
                issue = MetadataIssue(issue_type=issue_type, status="open", folder_path=str(request.folder_path))
            issue.metadata_job_id = uuid.UUID(request.job_id)
            issue.severity = severity
            issue.title = title
            issue.detail = detail
            issue.payload = payload
            session.add(issue)
            session.flush()
            issue_id = str(issue.id)
            session.commit()
            return issue_id

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
            job.error_stage = "ingest" if error else None
            job.error_reason = error
            session.add(job)
            session.commit()

    def _remove_marker_if_exists(self, folder_path: Path, marker_name: str) -> None:
        marker_path = folder_path / marker_name
        if marker_path.exists():
            marker_path.unlink()


def _normalize_alias(value: str) -> str:
    return " ".join(value.casefold().split())


def _candidate_issue_payload(candidate: ScoredProviderCandidate) -> dict[str, object]:
    result = candidate.result
    return {
        "provider_name": result.provider_name,
        "provider_id": result.provider_id,
        "media_shape": result.media_shape,
        "title": result.title,
        "original_title": result.original_title,
        "release_year": result.release_year,
        "popularity": result.popularity,
        "provider_rank": result.result_rank,
        "confidence_score": candidate.confidence_score,
        "raw_score_components": candidate.raw_score_components,
    }
