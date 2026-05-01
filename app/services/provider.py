from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass(frozen=True)
class ProviderSearchResult:
    provider_name: str
    provider_id: str
    media_shape: str
    title: str
    original_title: str | None = None
    overview: str | None = None
    release_date: date | None = None
    release_year: int | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None


@dataclass(frozen=True)
class ProviderEpisode:
    season_number: int
    episode_number: int
    title: str | None = None
    still_path: str | None = None


@dataclass(frozen=True)
class ProviderSeason:
    season_number: int
    poster_path: str | None = None
    episodes: list[ProviderEpisode] = field(default_factory=list)


@dataclass(frozen=True)
class ProviderDetails:
    provider_name: str
    provider_id: str
    media_shape: str
    title: str
    sort_title: str
    original_title: str | None
    overview: str | None
    release_date: date | None
    release_year: int | None
    runtime_minutes: int | None
    external_imdb_id: str | None
    poster_path: str | None
    backdrop_path: str | None
    seasons: list[ProviderSeason] = field(default_factory=list)
