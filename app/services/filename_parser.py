from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path


BRACKETED_JUNK_RE = re.compile(r"\[[^\]]+\]")
SEASON_EPISODE_RE = re.compile(r"(?i)(?:s(?P<season>\d{1,2})e(?P<episode>\d{1,2})|(?P<season_alt>\d{1,2})x(?P<episode_alt>\d{1,2}))")
YEAR_RE = re.compile(r"(?<!\d)(19\d{2}|20\d{2})(?!\d)")
SEASON_FOLDER_RE = re.compile(r"(?i)^(?:season\s*(?P<season>\d{1,2})|s(?P<season_alt>\d{1,2}))$")
MULTISPACE_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ParsedVideoFile:
    path: Path
    original_filename: str
    extension: str
    candidate_title: str
    season_number: int | None = None
    episode_number: int | None = None
    episode_title: str | None = None


def normalize_name(value: str) -> str:
    cleaned = BRACKETED_JUNK_RE.sub("", value).strip()
    cleaned = re.sub(r"[._-]+", " ", cleaned)
    cleaned = re.sub(r"[^\w\s()]", " ", cleaned)
    return MULTISPACE_RE.sub(" ", cleaned).strip()


def parse_season_folder_name(name: str) -> int | None:
    match = SEASON_FOLDER_RE.match(name.strip())
    if not match:
        return None
    season_value = match.group("season") or match.group("season_alt")
    return int(season_value)


def parse_movie_candidate(name: str) -> tuple[str, int | None]:
    normalized = normalize_name(name)
    year_match = YEAR_RE.search(normalized)
    year = int(year_match.group(1)) if year_match else None
    if year_match:
        title = normalized[: year_match.start()].strip(" -._(").strip()
    else:
        title = normalized
    return title, year


def parse_video_filename(path: Path) -> ParsedVideoFile:
    extension = path.suffix.lower()
    base_name = path.stem
    normalized = normalize_name(base_name)
    match = SEASON_EPISODE_RE.search(normalized)
    if match:
        season_text = match.group("season") or match.group("season_alt")
        episode_text = match.group("episode") or match.group("episode_alt")
        season_number = int(season_text)
        episode_number = int(episode_text)
        title_part = normalized[: match.start()].strip(" -")
        suffix_part = normalized[match.end() :].strip(" -")
        episode_title = suffix_part or None
        return ParsedVideoFile(
            path=path,
            original_filename=path.name,
            extension=extension,
            candidate_title=title_part,
            season_number=season_number,
            episode_number=episode_number,
            episode_title=episode_title,
        )

    movie_title, _ = parse_movie_candidate(base_name)
    return ParsedVideoFile(
        path=path,
        original_filename=path.name,
        extension=extension,
        candidate_title=movie_title,
    )


def build_film_sanitized_name(title: str, year: int | None, extension: str) -> str:
    if year is not None:
        return f"{title} ({year}){extension}"
    return f"{title}{extension}"


def build_episode_sanitized_name(
    title: str,
    season_number: int,
    episode_number: int,
    episode_title: str | None,
    extension: str,
) -> str:
    episode_code = f"S{season_number:02d}E{episode_number:02d}"
    if episode_title:
        return f"{title} - {episode_code} - {episode_title}{extension}"
    return f"{title} - {episode_code}{extension}"
