from datetime import date
from pathlib import Path

from app.services.filename_parser import ParsedVideoFile
from app.services.provider import ProviderSearchResult
from app.services.provider_matching import build_match_context, score_candidates, select_best_candidate


def test_obvious_movie_match_clears_threshold():
    parsed = [ParsedVideoFile(path=Path("Blade.Runner.1982.mkv"), original_filename="Blade.Runner.1982.mkv", extension=".mkv", candidate_title="Blade Runner")]
    context = build_match_context(candidate_title="Blade Runner", candidate_year=1982, library_category="movies", parsed_files=parsed)
    results = [
        ProviderSearchResult(
            provider_name="tmdb",
            provider_id="78",
            media_shape="film",
            title="Blade Runner",
            release_date=date(1982, 6, 25),
            release_year=1982,
            popularity=90.0,
            result_rank=1,
        )
    ]

    candidates = score_candidates(results, context)
    selection = select_best_candidate(candidates, confidence_threshold=0.72, ambiguity_delta=0.05)

    assert selection.selected is not None
    assert selection.selected.result.provider_id == "78"
    assert selection.selected.confidence_score >= 0.95


def test_low_confidence_match_is_rejected():
    parsed = [ParsedVideoFile(path=Path("Blade.Runner.1982.mkv"), original_filename="Blade.Runner.1982.mkv", extension=".mkv", candidate_title="Blade Runner")]
    context = build_match_context(candidate_title="Blade Runner", candidate_year=1982, library_category="movies", parsed_files=parsed)
    results = [
        ProviderSearchResult(
            provider_name="tmdb",
            provider_id="1",
            media_shape="series",
            title="Completely Different",
            release_year=2024,
            popularity=1.0,
            result_rank=1,
        )
    ]

    selection = select_best_candidate(score_candidates(results, context), confidence_threshold=0.72, ambiguity_delta=0.05)

    assert selection.selected is None
    assert selection.issue_type == "provider_low_confidence"


def test_close_candidates_are_ambiguous():
    parsed = [ParsedVideoFile(path=Path("Signal.Echo.S01E01.mkv"), original_filename="Signal.Echo.S01E01.mkv", extension=".mkv", candidate_title="Signal Echo", season_number=1, episode_number=1)]
    context = build_match_context(candidate_title="Signal Echo", candidate_year=None, library_category="series", parsed_files=parsed)
    results = [
        ProviderSearchResult(provider_name="tmdb", provider_id="1", media_shape="series", title="Signal Echo", result_rank=1),
        ProviderSearchResult(provider_name="tmdb", provider_id="2", media_shape="series", title="Signal Echo", result_rank=2),
    ]

    selection = select_best_candidate(score_candidates(results, context), confidence_threshold=0.72, ambiguity_delta=0.05)

    assert selection.selected is None
    assert selection.issue_type == "provider_ambiguous_match"
