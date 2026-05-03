from pathlib import Path

from app.config import load_config


def test_load_config(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
postgres:
  host: localhost
  port: 5432
  database: gregflix
  username: gregflix
  password_env: GREGFLIX_POSTGRES_PASSWORD
providers:
  tmdb:
    enabled: true
    api_key_env: TMDB_API_KEY
    base_url: https://api.themoviedb.org/3
    image_base_url: https://image.tmdb.org/t/p/original
image_storage:
  root_path: /tmp/images
libraries:
  - name: Movies
    category: movies
    path: /tmp/movies
    enabled: true
scanner:
  success_marker: gf-meta-tag
  failure_marker: gf-meta-failed
  supported_extensions: [.mkv, mp4]
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("GREGFLIX_POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("TMDB_API_KEY", "key")

    config = load_config(config_path)

    assert config.postgres.sqlalchemy_url().startswith("postgresql+psycopg://gregflix:secret@localhost")
    assert config.scanner.supported_extensions == [".mkv", ".mp4"]
    assert config.enabled_libraries[0].name == "Movies"
    assert config.artwork.preference == "prefer_provider"
    assert config.matching.confidence_threshold == 0.72


def test_load_artwork_preference(tmp_path: Path, monkeypatch):
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        """
postgres:
  host: localhost
  database: gregflix
  username: gregflix
  password_env: GREGFLIX_POSTGRES_PASSWORD
providers:
  tmdb:
    api_key_env: TMDB_API_KEY
    base_url: https://api.themoviedb.org/3
    image_base_url: https://image.tmdb.org/t/p/original
image_storage:
  root_path: /tmp/images
artwork:
  preference: prefer_local
libraries:
  - name: Movies
    category: movies
    path: /tmp/movies
scanner:
  supported_extensions: [.mkv]
        """.strip(),
        encoding="utf-8",
    )
    monkeypatch.setenv("GREGFLIX_POSTGRES_PASSWORD", "secret")
    monkeypatch.setenv("TMDB_API_KEY", "key")

    config = load_config(config_path)

    assert config.artwork.preference == "prefer_local"
