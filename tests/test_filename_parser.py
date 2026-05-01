from pathlib import Path

from app.services.filename_parser import parse_movie_candidate, parse_video_filename


def test_basic_movie_filename_parsing():
    parsed = parse_video_filename(Path("Blade.Runner.1982.1080p.BluRay.mkv"))

    assert parsed.candidate_title == "Blade Runner"
    assert parsed.season_number is None
    assert parsed.episode_number is None


def test_parenthesized_movie_year_parsing():
    title, year = parse_movie_candidate("Blade Runner (1982)")

    assert title == "Blade Runner"
    assert year == 1982


def test_bracketed_junk_is_removed():
    parsed = parse_video_filename(Path("[group]Blade-Runner-Sigma4!.mkv"))

    assert parsed.candidate_title == "Blade Runner Sigma4"


def test_basic_series_filename_parsing():
    parsed = parse_video_filename(Path("Show Name - S01E02 - Episode Title.mkv"))

    assert parsed.candidate_title == "Show Name"
    assert parsed.season_number == 1
    assert parsed.episode_number == 2
    assert parsed.episode_title == "Episode Title"
