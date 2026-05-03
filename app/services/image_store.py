from __future__ import annotations

import shutil
from pathlib import Path


class ImageStore:
    def __init__(self, root_path: Path) -> None:
        self.root_path = root_path.resolve()

    def movie_image_path(self, provider_name: str, provider_id: str, image_type: str) -> Path:
        return self.root_path / provider_name / "movie" / provider_id / f"{image_type}.jpg"

    def tv_image_path(self, provider_name: str, provider_id: str, image_type: str) -> Path:
        return self.root_path / provider_name / "tv" / provider_id / f"{image_type}.jpg"

    def season_image_path(self, provider_name: str, provider_id: str, season_number: int) -> Path:
        return self.root_path / provider_name / "tv" / provider_id / "seasons" / str(season_number) / "poster.jpg"

    def episode_still_path(self, provider_name: str, provider_id: str, season_number: int, episode_number: int) -> Path:
        episode_code = f"S{season_number:02d}E{episode_number:02d}"
        return self.root_path / provider_name / "tv" / provider_id / "episodes" / episode_code / "still.jpg"

    def local_artwork_path(
        self,
        *,
        media_shape: str,
        provider_id: str,
        source_path: Path,
        artwork_role: str,
        season_number: int | None = None,
        episode_number: int | None = None,
    ) -> Path:
        provider_kind = "tv" if media_shape == "series" else "movie"
        if artwork_role == "season_poster" and season_number is not None:
            return self.root_path / "local_file" / provider_kind / provider_id / "seasons" / str(season_number) / f"poster{source_path.suffix.lower()}"
        if artwork_role == "episode_still" and season_number is not None and episode_number is not None:
            episode_code = f"S{season_number:02d}E{episode_number:02d}"
            return self.root_path / "local_file" / provider_kind / provider_id / "episodes" / episode_code / f"still{source_path.suffix.lower()}"
        return self.root_path / "local_file" / provider_kind / provider_id / f"{artwork_role}{source_path.suffix.lower()}"

    def write_bytes(self, path: Path, content: bytes) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path.resolve()

    def copy_file(self, source_path: Path, target_path: Path) -> Path:
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if not target_path.exists():
            shutil.copy2(source_path, target_path)
        return target_path.resolve()
