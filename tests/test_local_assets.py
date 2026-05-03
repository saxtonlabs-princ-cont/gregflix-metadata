from pathlib import Path

from app.services.local_assets import classify_local_artwork, discover_local_assets


def test_classifies_root_artwork_names(tmp_path: Path):
    poster = tmp_path / "poster.jpg"
    fanart = tmp_path / "fanart.webp"
    logo = tmp_path / "logo.png"
    poster.write_text("", encoding="utf-8")
    fanart.write_text("", encoding="utf-8")
    logo.write_text("", encoding="utf-8")

    assert classify_local_artwork(poster).artwork_role == "poster"
    assert classify_local_artwork(fanart).artwork_role == "backdrop"
    assert classify_local_artwork(logo).artwork_role == "logo"


def test_classifies_season_and_episode_artwork(tmp_path: Path):
    season = tmp_path / "season01-poster.jpg"
    specials = tmp_path / "season-specials-poster.jpg"
    still = tmp_path / "Show.S01E02-still.jpg"

    season_artwork = classify_local_artwork(season)
    specials_artwork = classify_local_artwork(specials)
    still_artwork = classify_local_artwork(still)

    assert season_artwork.artwork_role == "season_poster"
    assert season_artwork.season_number == 1
    assert specials_artwork.artwork_role == "season_poster"
    assert specials_artwork.season_number == 0
    assert still_artwork.artwork_role == "episode_still"
    assert still_artwork.season_number == 1
    assert still_artwork.episode_number == 2


def test_discovers_local_metadata_files(tmp_path: Path):
    folder = tmp_path / "Movie"
    folder.mkdir()
    (folder / "poster.jpg").write_text("", encoding="utf-8")
    (folder / "movie.nfo").write_text("<movie />", encoding="utf-8")
    (folder / "metadata.json").write_text("{}", encoding="utf-8")

    discovery = discover_local_assets(folder)

    assert [item.artwork_role for item in discovery.artwork] == ["poster"]
    assert {item.metadata_type for item in discovery.metadata_files} == {"nfo", "json"}
