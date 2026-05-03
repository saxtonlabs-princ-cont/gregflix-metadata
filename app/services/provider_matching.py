from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.config import LibraryCategory
from app.services.filename_parser import ParsedVideoFile
from app.services.provider import ProviderSearchResult


NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class MatchContext:
    candidate_title: str
    candidate_year: int | None
    library_category: LibraryCategory
    expected_media_shape: str
    has_series_evidence: bool


@dataclass(frozen=True)
class ScoredProviderCandidate:
    result: ProviderSearchResult
    raw_score_components: dict[str, float | int | str | bool | None]
    confidence_score: float


@dataclass(frozen=True)
class CandidateSelection:
    selected: ScoredProviderCandidate | None
    candidates: list[ScoredProviderCandidate]
    issue_type: str | None = None
    issue_detail: str | None = None


def build_match_context(
    *,
    candidate_title: str,
    candidate_year: int | None,
    library_category: LibraryCategory,
    parsed_files: list[ParsedVideoFile],
) -> MatchContext:
    has_series_evidence = any(item.season_number is not None and item.episode_number is not None for item in parsed_files)
    expected_media_shape = "series" if has_series_evidence or library_category == "series" else "film"
    return MatchContext(
        candidate_title=candidate_title,
        candidate_year=candidate_year,
        library_category=library_category,
        expected_media_shape=expected_media_shape,
        has_series_evidence=has_series_evidence,
    )


def score_candidates(results: list[ProviderSearchResult], context: MatchContext) -> list[ScoredProviderCandidate]:
    scored = [score_candidate(result, context) for result in results]
    return sorted(scored, key=lambda item: item.confidence_score, reverse=True)


def score_candidate(result: ProviderSearchResult, context: MatchContext) -> ScoredProviderCandidate:
    title_similarity = max(
        _title_similarity(context.candidate_title, result.title),
        _title_similarity(context.candidate_title, result.original_title or ""),
    )
    year_match = _year_score(context.candidate_year, result.release_year)
    media_type_match = 1.0 if result.media_shape == context.expected_media_shape else 0.0
    library_hint = _library_hint_score(context.library_category, result.media_shape)
    series_evidence = 1.0 if not context.has_series_evidence or result.media_shape == "series" else 0.0
    rank_score = _rank_score(result.result_rank)
    popularity_score = _popularity_score(result.popularity)
    confidence = (
        title_similarity * 0.45
        + year_match * 0.15
        + media_type_match * 0.15
        + library_hint * 0.10
        + series_evidence * 0.10
        + rank_score * 0.03
        + popularity_score * 0.02
    )
    components: dict[str, float | int | str | bool | None] = {
        "candidate_title": context.candidate_title,
        "candidate_year": context.candidate_year,
        "expected_media_shape": context.expected_media_shape,
        "has_series_evidence": context.has_series_evidence,
        "title_similarity": round(title_similarity, 4),
        "year_match": year_match,
        "media_type_match": media_type_match,
        "library_hint": library_hint,
        "series_evidence": series_evidence,
        "rank_score": rank_score,
        "popularity_score": popularity_score,
    }
    return ScoredProviderCandidate(result=result, raw_score_components=components, confidence_score=round(confidence, 4))


def select_best_candidate(
    candidates: list[ScoredProviderCandidate],
    *,
    confidence_threshold: float,
    ambiguity_delta: float,
) -> CandidateSelection:
    if not candidates:
        return CandidateSelection(selected=None, candidates=[], issue_type="provider_no_match", issue_detail="Provider returned no candidates")
    best = candidates[0]
    if best.confidence_score < confidence_threshold:
        return CandidateSelection(
            selected=None,
            candidates=candidates,
            issue_type="provider_low_confidence",
            issue_detail=f"Best candidate score {best.confidence_score:.2f} is below threshold {confidence_threshold:.2f}",
        )
    if len(candidates) > 1 and best.confidence_score - candidates[1].confidence_score <= ambiguity_delta:
        return CandidateSelection(
            selected=None,
            candidates=candidates,
            issue_type="provider_ambiguous_match",
            issue_detail="Top provider candidates are too close to select automatically",
        )
    return CandidateSelection(selected=best, candidates=candidates)


def _title_similarity(left: str, right: str) -> float:
    normalized_left = _normalize_title(left)
    normalized_right = _normalize_title(right)
    if not normalized_left or not normalized_right:
        return 0.0
    if normalized_left == normalized_right:
        return 1.0
    return SequenceMatcher(None, normalized_left, normalized_right).ratio()


def _normalize_title(value: str) -> str:
    return NORMALIZE_RE.sub(" ", value.casefold()).strip()


def _year_score(candidate_year: int | None, result_year: int | None) -> float:
    if candidate_year is None or result_year is None:
        return 0.5
    if candidate_year == result_year:
        return 1.0
    if abs(candidate_year - result_year) == 1:
        return 0.75
    return 0.0


def _library_hint_score(library_category: str, media_shape: str) -> float:
    if library_category == "series":
        return 1.0 if media_shape == "series" else 0.0
    if library_category in {"movies", "documentaries"}:
        return 1.0 if media_shape == "film" else 0.25
    return 0.75


def _rank_score(rank: int | None) -> float:
    if rank is None:
        return 0.5
    return max(0.0, 1.0 - ((rank - 1) / 20.0))


def _popularity_score(popularity: float | None) -> float:
    if popularity is None:
        return 0.0
    return min(1.0, popularity / 100.0)
