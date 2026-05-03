"""catalog projections"""

from alembic import op


revision = "20260503_0006"
down_revision = "20260503_0005"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS catalog")
    op.execute(
        """
        CREATE TABLE catalog.catalog_row (
            id uuid PRIMARY KEY,
            row_key varchar(128) NOT NULL UNIQUE,
            title varchar(255) NOT NULL,
            description text,
            sort_order integer NOT NULL DEFAULT 0,
            visible boolean NOT NULL DEFAULT true,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_catalog_row_visible_sort ON catalog.catalog_row(sort_order, title) WHERE visible = true")
    op.execute(
        """
        CREATE TABLE catalog.catalog_row_item (
            id uuid PRIMARY KEY,
            catalog_row_id uuid NOT NULL REFERENCES catalog.catalog_row(id) ON DELETE CASCADE,
            entity_id uuid NOT NULL REFERENCES metadata.media_entity(id),
            sort_order integer NOT NULL DEFAULT 0,
            pinned boolean NOT NULL DEFAULT false,
            visible boolean NOT NULL DEFAULT true,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now(),
            CONSTRAINT uq_catalog_row_item UNIQUE (catalog_row_id, entity_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_catalog_row_item_row_visible_sort ON catalog.catalog_row_item(catalog_row_id, sort_order) WHERE visible = true")
    op.execute("CREATE INDEX ix_catalog_row_item_entity_id ON catalog.catalog_row_item(entity_id)")
    op.execute(
        """
        CREATE VIEW catalog.catalog_card_view AS
        SELECT
            e.id AS entity_id,
            e.entity_type,
            e.title,
            CASE
                WHEN e.entity_type = 'movie' THEN e.release_year::text
                WHEN e.entity_type = 'series' THEN e.release_year::text
                WHEN e.entity_type = 'season' THEN 'Season ' || lpad(e.season_number::text, 2, '0')
                WHEN e.entity_type = 'episode' THEN 'S' || lpad(e.season_number::text, 2, '0') || 'E' || lpad(e.episode_number::text, 2, '0')
                ELSE e.library_category
            END AS subtitle,
            e.release_date,
            e.release_year,
            e.library_category AS category,
            poster.stored_path AS poster_artwork_path,
            visual.stored_path AS backdrop_artwork_path,
            (e.metadata_fetched AND issue.id IS NULL) AS catalog_ready,
            (playable.entity_id IS NOT NULL) AS playable_available
        FROM metadata.media_entity e
        LEFT JOIN LATERAL (
            SELECT a.stored_path
            FROM metadata.artwork_asset a
            WHERE a.entity_id = e.id
              AND a.artwork_role IN ('poster', 'season_poster')
            ORDER BY a.preferred DESC, a.fallback_rank ASC, a.created_at ASC
            LIMIT 1
        ) poster ON true
        LEFT JOIN LATERAL (
            SELECT a.stored_path
            FROM metadata.artwork_asset a
            WHERE a.entity_id = e.id
              AND a.artwork_role IN ('backdrop', 'landscape')
            ORDER BY a.preferred DESC, a.fallback_rank ASC, a.created_at ASC
            LIMIT 1
        ) visual ON true
        LEFT JOIN LATERAL (
            SELECT i.id
            FROM metadata.metadata_issue i
            WHERE i.entity_id = e.id
              AND i.status = 'open'
            LIMIT 1
        ) issue ON true
        LEFT JOIN LATERAL (
            SELECT mf.entity_id
            FROM metadata.media_file mf
            WHERE mf.entity_id = e.id
            LIMIT 1
        ) playable ON true
        WHERE e.entity_type IN ('movie', 'series', 'season', 'episode', 'collection')
        """
    )
    op.execute(
        """
        CREATE VIEW catalog.media_detail_view AS
        SELECT
            e.id AS entity_id,
            e.entity_type,
            e.title,
            e.original_title,
            e.overview,
            e.release_date,
            CASE WHEN e.entity_type = 'series' THEN e.release_date ELSE NULL::date END AS start_date,
            NULL::date AS end_date,
            e.release_year,
            CASE
                WHEN e.entity_type IN ('movie', 'episode') THEN e.runtime_minutes
                ELSE NULL::integer
            END AS runtime_minutes,
            CASE
                WHEN e.entity_type = 'series' THEN season_counts.season_count
                ELSE NULL::integer
            END AS season_count,
            poster.stored_path AS poster_artwork_path,
            backdrop.stored_path AS backdrop_artwork_path,
            banner.stored_path AS banner_artwork_path,
            COALESCE(provider.provider_identities, '[]'::jsonb) AS provider_identity_summary
        FROM metadata.media_entity e
        LEFT JOIN LATERAL (
            SELECT count(*)::integer AS season_count
            FROM metadata.media_entity s
            WHERE s.parent_id = e.id
              AND s.entity_type = 'season'
        ) season_counts ON true
        LEFT JOIN LATERAL (
            SELECT a.stored_path
            FROM metadata.artwork_asset a
            WHERE a.entity_id = e.id
              AND a.artwork_role IN ('poster', 'season_poster')
            ORDER BY a.preferred DESC, a.fallback_rank ASC, a.created_at ASC
            LIMIT 1
        ) poster ON true
        LEFT JOIN LATERAL (
            SELECT a.stored_path
            FROM metadata.artwork_asset a
            WHERE a.entity_id = e.id
              AND a.artwork_role = 'backdrop'
            ORDER BY a.preferred DESC, a.fallback_rank ASC, a.created_at ASC
            LIMIT 1
        ) backdrop ON true
        LEFT JOIN LATERAL (
            SELECT a.stored_path
            FROM metadata.artwork_asset a
            WHERE a.entity_id = e.id
              AND a.artwork_role = 'banner'
            ORDER BY a.preferred DESC, a.fallback_rank ASC, a.created_at ASC
            LIMIT 1
        ) banner ON true
        LEFT JOIN LATERAL (
            SELECT jsonb_agg(
                jsonb_build_object(
                    'provider', p.provider_name,
                    'provider_media_type', p.provider_media_type,
                    'provider_id', p.provider_id,
                    'primary', p.primary_identity
                )
                ORDER BY p.primary_identity DESC, p.provider_name
            ) AS provider_identities
            FROM metadata.provider_identity p
            WHERE p.entity_id = e.id
        ) provider ON true
        WHERE e.entity_type IN ('movie', 'series', 'season', 'episode', 'collection')
        """
    )
    op.execute(
        """
        CREATE VIEW catalog.series_episode_view AS
        SELECT
            series.id AS series_id,
            season.id AS season_id,
            episode.id AS episode_id,
            season.season_number,
            episode.episode_number,
            episode.title AS episode_title,
            episode.overview,
            still.stored_path AS still_image_path,
            (playable.entity_id IS NOT NULL) AS playable_file_available
        FROM metadata.media_entity series
        JOIN metadata.media_entity season
          ON season.parent_id = series.id
         AND season.entity_type = 'season'
        JOIN metadata.media_entity episode
          ON episode.parent_id = season.id
         AND episode.entity_type = 'episode'
        LEFT JOIN LATERAL (
            SELECT a.stored_path
            FROM metadata.artwork_asset a
            WHERE a.entity_id = episode.id
              AND a.artwork_role = 'episode_still'
            ORDER BY a.preferred DESC, a.fallback_rank ASC, a.created_at ASC
            LIMIT 1
        ) still ON true
        LEFT JOIN LATERAL (
            SELECT mf.entity_id
            FROM metadata.media_file mf
            WHERE mf.entity_id = episode.id
            LIMIT 1
        ) playable ON true
        WHERE series.entity_type = 'series'
        """
    )


def downgrade():
    op.execute("DROP VIEW catalog.series_episode_view")
    op.execute("DROP VIEW catalog.media_detail_view")
    op.execute("DROP VIEW catalog.catalog_card_view")
    op.execute("DROP TABLE catalog.catalog_row_item")
    op.execute("DROP TABLE catalog.catalog_row")
