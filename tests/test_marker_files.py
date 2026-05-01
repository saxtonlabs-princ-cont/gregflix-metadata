from pathlib import Path

from app.services.marker_files import build_failure_marker_content, detect_marker_state


def test_marker_detection(tmp_path: Path):
    folder = tmp_path / "Movie"
    folder.mkdir()
    (folder / "gf-meta-tag").write_text("ok", encoding="utf-8")

    state = detect_marker_state(folder, "gf-meta-tag", "gf-meta-failed")

    assert state.success_exists is True
    assert state.failure_exists is False
    assert state.should_skip is True


def test_failure_marker_content(tmp_path: Path):
    folder = tmp_path / "Broken"
    payload = build_failure_marker_content(
        library_name="Movies",
        library_category="movies",
        folder_path=folder,
        raw_folder_name="Broken",
        raw_filenames=["Broken.mkv"],
        extracted_candidate_title="Broken",
        failure_stage="provider_lookup",
        failure_reason="No TMDB results",
        exception=LookupError("No TMDB results"),
        provider_response_count=0,
    )

    assert payload["job_status"] == "failed"
    assert payload["failure_stage"] == "provider_lookup"
    assert payload["provider_response_count"] == 0
    assert payload["exception"]["type"] == "LookupError"
