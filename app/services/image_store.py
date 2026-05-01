from __future__ import annotations

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

    def write_bytes(self, path: Path, content: bytes) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
        return path.resolve()
