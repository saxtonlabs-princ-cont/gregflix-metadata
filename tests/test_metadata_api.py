from pathlib import Path

import pytest
from fastapi import HTTPException

from app.api.metadata import _validated_library_folder
from app.main import app
from tests.test_scanner import build_config


def test_metadata_trigger_routes_are_registered():
    paths = {route.path for route in app.routes}

    assert "/jobs/{job_id}/retry" in paths
    assert "/metadata/index-path" in paths
    assert "/metadata/retry-path" in paths
    assert "/metadata/entities/{entity_id}/refresh-provider" in paths
    assert "/metadata/entities/{entity_id}/refresh-artwork" in paths
    assert "/metadata/issues" in paths
    assert "/metadata/diagnostics" in paths


def test_validated_library_folder_rejects_outside_path(tmp_path: Path):
    config = build_config(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()

    with pytest.raises(HTTPException) as exc:
        _validated_library_folder(config, str(outside))

    assert exc.value.status_code == 400


def test_validated_library_folder_maps_descendant_to_top_level_media_folder(tmp_path: Path):
    config = build_config(tmp_path)
    library = config.enabled_libraries[0]
    media_folder = library.path / "Movie"
    nested = media_folder / "Extras"
    nested.mkdir(parents=True)

    resolved_library, resolved_folder = _validated_library_folder(config, str(nested))

    assert resolved_library.name == library.name
    assert resolved_folder == media_folder.resolve()
