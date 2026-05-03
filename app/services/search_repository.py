from __future__ import annotations

import re
import uuid
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session


NORMALIZE_RE = re.compile(r"[^a-z0-9]+")


@dataclass(frozen=True)
class SearchResult:
    entity_id: uuid.UUID
    entity_type: str
    display_title: str
    release_year: int | None
    library_category: str | None
    rank: float


def normalize_search_text(value: str) -> str:
    return NORMALIZE_RE.sub(" ", value.casefold()).strip()


def refresh_search_documents(session: Session, entity_ids: list[uuid.UUID]) -> None:
    if not entity_ids:
        return
    session.execute(
        text(
            """
            INSERT INTO catalog.search_document (
                entity_id,
                entity_type,
                display_title,
                normalized_title,
                aliases,
                aliases_text,
                release_year,
                library_category,
                description,
                searchable_text,
                search_vector,
                visible,
                updated_at
            )
            SELECT
                e.id,
                e.entity_type,
                e.title,
                lower(unaccent(e.title)),
                COALESCE(array_agg(a.alias ORDER BY a.is_primary DESC, a.alias) FILTER (WHERE a.alias IS NOT NULL), '{}'),
                COALESCE(string_agg(a.alias, ' ' ORDER BY a.is_primary DESC, a.alias), ''),
                e.release_year,
                e.library_category,
                e.overview,
                concat_ws(' ', e.title, e.original_title, e.release_year::text, e.library_category, e.overview, string_agg(a.alias, ' ')),
                to_tsvector(
                    'simple',
                    unaccent(concat_ws(' ', e.title, e.original_title, e.release_year::text, e.library_category, e.overview, string_agg(a.alias, ' ')))
                ),
                true,
                now()
            FROM metadata.media_entity e
            LEFT JOIN metadata.entity_alias a ON a.entity_id = e.id
            WHERE e.id = ANY(:entity_ids)
            GROUP BY e.id
            ON CONFLICT (entity_id) DO UPDATE SET
                entity_type = EXCLUDED.entity_type,
                display_title = EXCLUDED.display_title,
                normalized_title = EXCLUDED.normalized_title,
                aliases = EXCLUDED.aliases,
                aliases_text = EXCLUDED.aliases_text,
                release_year = EXCLUDED.release_year,
                library_category = EXCLUDED.library_category,
                description = EXCLUDED.description,
                searchable_text = EXCLUDED.searchable_text,
                search_vector = EXCLUDED.search_vector,
                visible = EXCLUDED.visible,
                updated_at = now()
            """
        ),
        {"entity_ids": entity_ids},
    )


def title_autocomplete(session: Session, prefix: str, *, limit: int = 10) -> list[SearchResult]:
    rows = session.execute(
        text(
            """
            SELECT entity_id, entity_type, display_title, release_year, library_category, 1.0::float AS rank
            FROM catalog.search_document
            WHERE visible = true
              AND normalized_title LIKE lower(unaccent(:prefix)) || '%'
            ORDER BY display_title
            LIMIT :limit
            """
        ),
        {"prefix": normalize_search_text(prefix), "limit": limit},
    )
    return [_row_to_result(row) for row in rows]


def full_search(session: Session, query: str, *, limit: int = 20) -> list[SearchResult]:
    rows = session.execute(
        text(
            """
            SELECT
                entity_id,
                entity_type,
                display_title,
                release_year,
                library_category,
                ts_rank(search_vector, plainto_tsquery('simple', unaccent(:query)))::float AS rank
            FROM catalog.search_document
            WHERE visible = true
              AND search_vector @@ plainto_tsquery('simple', unaccent(:query))
            ORDER BY rank DESC, display_title
            LIMIT :limit
            """
        ),
        {"query": query, "limit": limit},
    )
    return [_row_to_result(row) for row in rows]


def fuzzy_title_lookup(session: Session, title: str, *, limit: int = 10) -> list[SearchResult]:
    rows = session.execute(
        text(
            """
            SELECT
                entity_id,
                entity_type,
                display_title,
                release_year,
                library_category,
                greatest(
                    similarity(normalized_title, lower(unaccent(:title))),
                    similarity(aliases_text, lower(unaccent(:title)))
                )::float AS rank
            FROM catalog.search_document
            WHERE visible = true
              AND (
                normalized_title % lower(unaccent(:title))
                OR aliases_text % lower(unaccent(:title))
              )
            ORDER BY rank DESC, display_title
            LIMIT :limit
            """
        ),
        {"title": normalize_search_text(title), "limit": limit},
    )
    return [_row_to_result(row) for row in rows]


def _row_to_result(row) -> SearchResult:
    return SearchResult(
        entity_id=row.entity_id,
        entity_type=row.entity_type,
        display_title=row.display_title,
        release_year=row.release_year,
        library_category=row.library_category,
        rank=float(row.rank or 0.0),
    )
