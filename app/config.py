from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


LibraryCategory = Literal["movies", "series", "anime", "documentaries"]
MediaShape = Literal["film", "series"]
ArtworkPreference = Literal["prefer_local", "prefer_provider", "provider_only", "local_only"]


class PostgresConfig(BaseModel):
    host: str
    port: int = 5432
    database: str
    username: str
    password_env: str

    def password(self) -> SecretStr:
        value = os.environ.get(self.password_env)
        if not value:
            raise ValueError(f"Missing database password environment variable: {self.password_env}")
        return SecretStr(value)

    def sqlalchemy_url(self) -> str:
        password = self.password().get_secret_value()
        return f"postgresql+psycopg://{self.username}:{password}@{self.host}:{self.port}/{self.database}"


class TmdbProviderConfig(BaseModel):
    enabled: bool = True
    api_key_env: str
    base_url: str
    image_base_url: str

    def api_key(self) -> SecretStr:
        value = os.environ.get(self.api_key_env)
        if not value:
            raise ValueError(f"Missing TMDB API key environment variable: {self.api_key_env}")
        return SecretStr(value)


class ProvidersConfig(BaseModel):
    tmdb: TmdbProviderConfig


class ImageStorageConfig(BaseModel):
    root_path: Path


class LibraryConfig(BaseModel):
    name: str
    category: LibraryCategory
    path: Path
    enabled: bool = True


class ScannerConfig(BaseModel):
    success_marker: str = "gf-meta-tag"
    failure_marker: str = "gf-meta-failed"
    supported_extensions: list[str] = Field(default_factory=list)

    @field_validator("supported_extensions")
    @classmethod
    def normalize_extensions(cls, values: list[str]) -> list[str]:
        normalized = []
        for value in values:
            ext = value.lower()
            if not ext.startswith("."):
                ext = f".{ext}"
            normalized.append(ext)
        return normalized


class ArtworkConfig(BaseModel):
    preference: ArtworkPreference = "prefer_provider"


class MatchingConfig(BaseModel):
    confidence_threshold: float = 0.72
    ambiguity_delta: float = 0.05


class AppConfig(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)

    postgres: PostgresConfig
    providers: ProvidersConfig
    image_storage: ImageStorageConfig
    libraries: list[LibraryConfig]
    scanner: ScannerConfig
    artwork: ArtworkConfig = Field(default_factory=ArtworkConfig)
    matching: MatchingConfig = Field(default_factory=MatchingConfig)

    @property
    def enabled_libraries(self) -> list[LibraryConfig]:
        return [library for library in self.libraries if library.enabled]


def get_config_path() -> Path:
    configured = os.environ.get("GREGFLIX_METADATA_CONFIG", "./config.yaml")
    return Path(configured).expanduser().resolve()


def load_config(config_path: Path | None = None) -> AppConfig:
    path = config_path or get_config_path()
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle) or {}
    return AppConfig.model_validate(payload)


@lru_cache(maxsize=1)
def get_config() -> AppConfig:
    return load_config()
