"""search documents"""

from alembic import op


revision = "20260503_0005"
down_revision = "20260503_0004"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")
    op.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
    op.execute(
        """
        CREATE TABLE catalog.search_document (
            entity_id uuid PRIMARY KEY REFERENCES metadata.media_entity(id),
            entity_type varchar(32) NOT NULL,
            display_title varchar(512) NOT NULL,
            normalized_title varchar(512) NOT NULL,
            aliases text[] NOT NULL DEFAULT '{}',
            aliases_text text NOT NULL DEFAULT '',
            release_year integer,
            library_category varchar(32),
            description text,
            searchable_text text NOT NULL,
            search_vector tsvector NOT NULL,
            visible boolean NOT NULL DEFAULT true,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_search_document_vector ON catalog.search_document USING gin(search_vector)")
    op.execute("CREATE INDEX ix_search_document_normalized_title_trgm ON catalog.search_document USING gin(normalized_title gin_trgm_ops)")
    op.execute("CREATE INDEX ix_search_document_aliases_text_trgm ON catalog.search_document USING gin(aliases_text gin_trgm_ops)")
    op.execute(
        """
        CREATE INDEX ix_search_document_visible_title
        ON catalog.search_document(entity_type, library_category, release_year)
        WHERE visible = true
        """
    )
    op.execute(
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
            visible
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
            to_tsvector('simple', unaccent(concat_ws(' ', e.title, e.original_title, e.release_year::text, e.library_category, e.overview, string_agg(a.alias, ' ')))),
            true
        FROM metadata.media_entity e
        LEFT JOIN metadata.entity_alias a ON a.entity_id = e.id
        WHERE e.entity_type IN ('movie', 'series', 'season', 'episode', 'collection')
        GROUP BY e.id
        """
    )


def downgrade():
    op.execute("DROP TABLE catalog.search_document")
