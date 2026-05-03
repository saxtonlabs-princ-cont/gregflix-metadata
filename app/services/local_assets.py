from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


ARTWORK_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
METADATA_EXTENSIONS = {".nfo", ".xml", ".json"}
SEASON_POSTER_RE = re.compile(r"^season[-_. ]?(?P<season>\d{1,2}|specials)-poster$", re.IGNORECASE)
EPISODE_STILL_RE = re.compile(r"^(?:.*[-_. ])?s(?P<season>\d{1,2})e(?P<episode>\d{1,2})[-_. ](?:still|thumb|thumbnail)$", re.IGNORECASE)


@dataclass(frozen=True)
class LocalArtwork:
    source_path: Path
    artwork_role: str
    season_number: int | None = None
    episode_number: int | None = None


@dataclass(frozen=True)
class LocalMetadataFile:
    source_path: Path
    metadata_type: str


@dataclass(frozen=True)
class LocalAssetDiscovery:
    artwork: list[LocalArtwork]
    metadata_files: list[LocalMetadataFile]


def discover_local_assets(folder_path: Path) -> LocalAssetDiscovery:
    artwork: list[LocalArtwork] = []
    metadata_files: list[LocalMetadataFile] = []
    for path in sorted(folder_path.rglob("*")):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix in ARTWORK_EXTENSIONS:
            local_artwork = classify_local_artwork(path)
            if local_artwork is not None:
                artwork.append(local_artwork)
        elif suffix in METADATA_EXTENSIONS:
            metadata_files.append(LocalMetadataFile(source_path=path.resolve(), metadata_type=suffix.removeprefix(".")))
    return LocalAssetDiscovery(artwork=artwork, metadata_files=metadata_files)


def classify_local_artwork(path: Path) -> LocalArtwork | None:
    name = path.stem.casefold()
    if name in {"poster", "cover", "folder"}:
        return LocalArtwork(source_path=path.resolve(), artwork_role="poster")
    if name in {"backdrop", "fanart"}:
        return LocalArtwork(source_path=path.resolve(), artwork_role="backdrop")
    if name == "landscape":
        return LocalArtwork(source_path=path.resolve(), artwork_role="landscape")
    if name == "banner":
        return LocalArtwork(source_path=path.resolve(), artwork_role="banner")
    if name == "logo":
        return LocalArtwork(source_path=path.resolve(), artwork_role="logo")

    season_match = SEASON_POSTER_RE.match(name)
    if season_match:
        season_text = season_match.group("season")
        season_number = 0 if season_text == "specials" else int(season_text)
        return LocalArtwork(source_path=path.resolve(), artwork_role="season_poster", season_number=season_number)

    episode_match = EPISODE_STILL_RE.match(name)
    if episode_match:
        return LocalArtwork(
            source_path=path.resolve(),
            artwork_role="episode_still",
            season_number=int(episode_match.group("season")),
            episode_number=int(episode_match.group("episode")),
        )
    return None
