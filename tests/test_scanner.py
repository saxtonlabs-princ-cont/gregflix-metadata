from pathlib import Path

from app.config import AppConfig
from app.services.scanner import LibraryScanner


def build_config(tmp_path: Path) -> AppConfig:
    library_root = tmp_path / "movies"
    library_root.mkdir()
    return AppConfig.model_validate(
        {
            "postgres": {
                "host": "localhost",
                "port": 5432,
                "database": "gregflix",
                "username": "gregflix",
                "password_env": "DB_PASSWORD",
            },
            "providers": {
                "tmdb": {
                    "enabled": True,
                    "api_key_env": "TMDB_API_KEY",
                    "base_url": "https://api.themoviedb.org/3",
                    "image_base_url": "https://image.tmdb.org/t/p/original",
                }
            },
            "image_storage": {"root_path": str(tmp_path / "images")},
            "libraries": [
                {"name": "Movies", "category": "movies", "path": str(library_root), "enabled": True},
            ],
            "scanner": {
                "success_marker": "gf-meta-tag",
                "failure_marker": "gf-meta-failed",
                "supported_extensions": [".mkv", ".mp4"],
            },
        }
    )


def test_folder_skip_logic(tmp_path: Path):
    config = build_config(tmp_path)
    scanner = LibraryScanner(config)
    library_root = config.enabled_libraries[0].path

    success = library_root / "Done"
    success.mkdir()
    (success / "gf-meta-tag").write_text("ok", encoding="utf-8")

    failed = library_root / "Failed"
    failed.mkdir()
    (failed / "gf-meta-failed").write_text("bad", encoding="utf-8")

    invalid = library_root / "Invalid"
    invalid.mkdir()
    (invalid / "gf-meta-tag").write_text("ok", encoding="utf-8")
    (invalid / "gf-meta-failed").write_text("bad", encoding="utf-8")

    pending = library_root / "Pending"
    pending.mkdir()

    summary = scanner.scan_all()

    assert summary.skipped_success == 1
    assert summary.skipped_failure == 1
    assert summary.skipped_invalid == 1
    assert len(summary.queued) == 1
    assert summary.queued[0].folder_path == pending.resolve()


def test_supported_extension_filtering(tmp_path: Path):
    config = build_config(tmp_path)
    scanner = LibraryScanner(config)
    mkv_file = tmp_path / "movie.mkv"
    txt_file = tmp_path / "notes.txt"
    mkv_file.write_text("", encoding="utf-8")
    txt_file.write_text("", encoding="utf-8")

    assert scanner.should_include_file(mkv_file) is True
    assert scanner.should_include_file(txt_file) is False
