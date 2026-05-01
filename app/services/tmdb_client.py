from __future__ import annotations

from datetime import date
from typing import Any

import httpx

from app.config import TmdbProviderConfig
from app.services.provider import ProviderDetails, ProviderEpisode, ProviderSearchResult, ProviderSeason


class TmdbClient:
    provider_name = "tmdb"

    def __init__(self, config: TmdbProviderConfig) -> None:
        self.config = config
        self.api_key = config.api_key().get_secret_value()

    async def _get(self, path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        request_params = {"api_key": self.api_key}
        if params:
            request_params.update(params)
        async with httpx.AsyncClient(base_url=self.config.base_url, timeout=30.0) as client:
            response = await client.get(path, params=request_params)
            response.raise_for_status()
            return response.json()

    async def search_movie(self, query: str) -> list[ProviderSearchResult]:
        payload = await self._get("/search/movie", {"query": query})
        return [self._movie_search_result(item) for item in payload.get("results", [])]

    async def search_tv(self, query: str) -> list[ProviderSearchResult]:
        payload = await self._get("/search/tv", {"query": query})
        return [self._tv_search_result(item) for item in payload.get("results", [])]

    async def get_movie_details(self, provider_id: str) -> ProviderDetails:
        payload = await self._get(f"/movie/{provider_id}")
        return ProviderDetails(
            provider_name=self.provider_name,
            provider_id=str(payload["id"]),
            media_shape="film",
            title=payload["title"],
            sort_title=payload["title"],
            original_title=payload.get("original_title"),
            overview=payload.get("overview"),
            release_date=_parse_date(payload.get("release_date")),
            release_year=_parse_year(payload.get("release_date")),
            runtime_minutes=payload.get("runtime"),
            external_imdb_id=payload.get("imdb_id"),
            poster_path=payload.get("poster_path"),
            backdrop_path=payload.get("backdrop_path"),
        )

    async def get_tv_details(self, provider_id: str) -> ProviderDetails:
        payload = await self._get(f"/tv/{provider_id}")
        seasons: list[ProviderSeason] = []
        for season in payload.get("seasons", []):
            season_number = season.get("season_number")
            if season_number is None or season_number < 0:
                continue
            season_details = await self.get_season_details(str(payload["id"]), int(season_number))
            seasons.append(season_details)
        return ProviderDetails(
            provider_name=self.provider_name,
            provider_id=str(payload["id"]),
            media_shape="series",
            title=payload["name"],
            sort_title=payload["name"],
            original_title=payload.get("original_name"),
            overview=payload.get("overview"),
            release_date=_parse_date(payload.get("first_air_date")),
            release_year=_parse_year(payload.get("first_air_date")),
            runtime_minutes=(payload.get("episode_run_time") or [None])[0],
            external_imdb_id=None,
            poster_path=payload.get("poster_path"),
            backdrop_path=payload.get("backdrop_path"),
            seasons=seasons,
        )

    async def get_season_details(self, provider_id: str, season_number: int) -> ProviderSeason:
        payload = await self._get(f"/tv/{provider_id}/season/{season_number}")
        episodes = [
            ProviderEpisode(
                season_number=episode["season_number"],
                episode_number=episode["episode_number"],
                title=episode.get("name"),
                still_path=episode.get("still_path"),
            )
            for episode in payload.get("episodes", [])
        ]
        return ProviderSeason(
            season_number=payload["season_number"],
            poster_path=payload.get("poster_path"),
            episodes=episodes,
        )

    def image_url(self, relative_path: str | None) -> str | None:
        if not relative_path:
            return None
        return f"{self.config.image_base_url}{relative_path}"

    async def download_image(self, image_url: str) -> bytes:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(image_url)
            response.raise_for_status()
            return response.content

    def _movie_search_result(self, payload: dict[str, Any]) -> ProviderSearchResult:
        return ProviderSearchResult(
            provider_name=self.provider_name,
            provider_id=str(payload["id"]),
            media_shape="film",
            title=payload["title"],
            original_title=payload.get("original_title"),
            overview=payload.get("overview"),
            release_date=_parse_date(payload.get("release_date")),
            release_year=_parse_year(payload.get("release_date")),
            poster_path=payload.get("poster_path"),
            backdrop_path=payload.get("backdrop_path"),
        )

    def _tv_search_result(self, payload: dict[str, Any]) -> ProviderSearchResult:
        return ProviderSearchResult(
            provider_name=self.provider_name,
            provider_id=str(payload["id"]),
            media_shape="series",
            title=payload["name"],
            original_title=payload.get("original_name"),
            overview=payload.get("overview"),
            release_date=_parse_date(payload.get("first_air_date")),
            release_year=_parse_year(payload.get("first_air_date")),
            poster_path=payload.get("poster_path"),
            backdrop_path=payload.get("backdrop_path"),
        )


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value)


def _parse_year(value: str | None) -> int | None:
    parsed = _parse_date(value)
    return parsed.year if parsed else None
