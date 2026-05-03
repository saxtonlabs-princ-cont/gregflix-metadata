"""canonical metadata schema"""

from alembic import op


revision = "20260503_0002"
down_revision = "20260501_0001"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("CREATE SCHEMA IF NOT EXISTS metadata")
    op.execute("CREATE SCHEMA IF NOT EXISTS catalog")
    op.execute(
        """
        CREATE TABLE metadata.media_entity (
            id uuid PRIMARY KEY,
            entity_type varchar(32) NOT NULL,
            parent_id uuid REFERENCES metadata.media_entity(id),
            library_category varchar(32),
            title varchar(512) NOT NULL,
            sort_title varchar(512) NOT NULL,
            original_title varchar(512),
            overview text,
            release_date date,
            release_year integer,
            runtime_minutes integer,
            season_number integer,
            episode_number integer,
            metadata_fetched boolean NOT NULL DEFAULT false,
            metadata_fetched_at timestamp with time zone,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now(),
            CONSTRAINT ck_media_entity_type
                CHECK (entity_type IN ('movie', 'series', 'season', 'episode', 'collection'))
        )
        """
    )
    op.execute("CREATE INDEX ix_media_entity_parent_id ON metadata.media_entity(parent_id)")
    op.execute("CREATE INDEX ix_media_entity_type ON metadata.media_entity(entity_type)")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_media_entity_parent_season
        ON metadata.media_entity(parent_id, season_number)
        WHERE entity_type = 'season' AND season_number IS NOT NULL
        """
    )
    op.execute(
        """
        CREATE UNIQUE INDEX uq_media_entity_parent_episode
        ON metadata.media_entity(parent_id, season_number, episode_number)
        WHERE entity_type = 'episode' AND season_number IS NOT NULL AND episode_number IS NOT NULL
        """
    )

    op.execute(
        """
        CREATE TABLE metadata.provider_identity (
            id uuid PRIMARY KEY,
            entity_id uuid NOT NULL REFERENCES metadata.media_entity(id),
            provider_name varchar(64) NOT NULL,
            provider_media_type varchar(32) NOT NULL,
            provider_id varchar(128) NOT NULL,
            external_url varchar(2048),
            primary_identity boolean NOT NULL DEFAULT false,
            payload jsonb,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now(),
            CONSTRAINT uq_provider_identity
                UNIQUE (provider_name, provider_media_type, provider_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_provider_identity_entity_id ON metadata.provider_identity(entity_id)")

    op.execute(
        """
        CREATE TABLE metadata.entity_alias (
            id uuid PRIMARY KEY,
            entity_id uuid NOT NULL REFERENCES metadata.media_entity(id),
            alias varchar(512) NOT NULL,
            normalized_alias varchar(512) NOT NULL,
            locale varchar(32),
            source varchar(64) NOT NULL,
            is_primary boolean NOT NULL DEFAULT false,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            CONSTRAINT uq_entity_alias
                UNIQUE (entity_id, normalized_alias, source)
        )
        """
    )
    op.execute("CREATE INDEX ix_entity_alias_normalized_alias ON metadata.entity_alias(normalized_alias)")

    op.execute(
        """
        CREATE TABLE metadata.media_file (
            id uuid PRIMARY KEY,
            entity_id uuid NOT NULL REFERENCES metadata.media_entity(id),
            original_path varchar(2048) NOT NULL UNIQUE,
            original_filename varchar(512) NOT NULL,
            sanitized_name varchar(512) NOT NULL,
            extension varchar(32) NOT NULL,
            size_bytes bigint,
            season_number integer,
            episode_number integer,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_media_file_entity_id ON metadata.media_file(entity_id)")

    op.execute(
        """
        CREATE TABLE metadata.artwork_asset (
            id uuid PRIMARY KEY,
            entity_id uuid NOT NULL REFERENCES metadata.media_entity(id),
            artwork_role varchar(32) NOT NULL,
            source varchar(64) NOT NULL,
            source_provider_id varchar(128),
            original_path varchar(2048),
            stored_path varchar(2048) NOT NULL UNIQUE,
            preferred boolean NOT NULL DEFAULT false,
            fallback_rank integer NOT NULL DEFAULT 0,
            width integer,
            height integer,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_artwork_asset_entity_id ON metadata.artwork_asset(entity_id)")

    op.execute(
        """
        CREATE TABLE metadata.metadata_evidence (
            id uuid PRIMARY KEY,
            entity_id uuid REFERENCES metadata.media_entity(id),
            metadata_job_id uuid REFERENCES metadata_jobs(id),
            evidence_type varchar(64) NOT NULL,
            source varchar(64) NOT NULL,
            summary text,
            payload jsonb,
            created_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_metadata_evidence_entity_id ON metadata.metadata_evidence(entity_id)")
    op.execute("CREATE INDEX ix_metadata_evidence_job_id ON metadata.metadata_evidence(metadata_job_id)")

    op.execute(
        """
        CREATE TABLE metadata.metadata_issue (
            id uuid PRIMARY KEY,
            entity_id uuid REFERENCES metadata.media_entity(id),
            metadata_job_id uuid REFERENCES metadata_jobs(id),
            issue_type varchar(64) NOT NULL,
            severity varchar(32) NOT NULL,
            status varchar(32) NOT NULL DEFAULT 'open',
            title varchar(512) NOT NULL,
            detail text,
            folder_path varchar(2048),
            payload jsonb,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_metadata_issue_entity_id ON metadata.metadata_issue(entity_id)")
    op.execute("CREATE INDEX ix_metadata_issue_status ON metadata.metadata_issue(status)")
    op.execute("CREATE INDEX ix_metadata_issue_job_id ON metadata.metadata_issue(metadata_job_id)")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION pg_temp.gf_migration_uuid(value text)
        RETURNS uuid
        LANGUAGE SQL
        AS $$
            SELECT (
                substr(md5(value), 1, 8) || '-' ||
                substr(md5(value), 9, 4) || '-' ||
                substr(md5(value), 13, 4) || '-' ||
                substr(md5(value), 17, 4) || '-' ||
                substr(md5(value), 21, 12)
            )::uuid
        $$
        """
    )
    op.execute(
        """
        INSERT INTO metadata.media_entity (
            id,
            entity_type,
            library_category,
            title,
            sort_title,
            original_title,
            overview,
            release_date,
            release_year,
            runtime_minutes,
            metadata_fetched,
            metadata_fetched_at,
            created_at,
            updated_at
        )
        SELECT
            id,
            CASE WHEN media_shape = 'series' THEN 'series' ELSE 'movie' END,
            library_category,
            title,
            sort_title,
            original_title,
            overview,
            release_date,
            release_year,
            runtime_minutes,
            metadata_fetched,
            metadata_fetched_at,
            created_at,
            updated_at
        FROM media_items
        """
    )
    op.execute(
        """
        INSERT INTO metadata.media_entity (
            id,
            entity_type,
            parent_id,
            library_category,
            title,
            sort_title,
            season_number,
            metadata_fetched,
            metadata_fetched_at
        )
        SELECT
            pg_temp.gf_migration_uuid('season:' || mi.id::text || ':' || mf.season_number::text),
            'season',
            mi.id,
            mi.library_category,
            mi.title || ' - Season ' || lpad(mf.season_number::text, 2, '0'),
            mi.sort_title || ' - Season ' || lpad(mf.season_number::text, 2, '0'),
            mf.season_number,
            mi.metadata_fetched,
            mi.metadata_fetched_at
        FROM media_items mi
        JOIN media_files mf ON mf.media_item_id = mi.id
        WHERE mi.media_shape = 'series'
          AND mf.season_number IS NOT NULL
        GROUP BY mi.id, mi.library_category, mi.title, mi.sort_title, mf.season_number, mi.metadata_fetched, mi.metadata_fetched_at
        """
    )
    op.execute(
        """
        INSERT INTO metadata.media_entity (
            id,
            entity_type,
            parent_id,
            library_category,
            title,
            sort_title,
            season_number,
            episode_number,
            metadata_fetched,
            metadata_fetched_at
        )
        SELECT
            pg_temp.gf_migration_uuid(
                'episode:' || mi.id::text || ':' || mf.season_number::text || ':' || mf.episode_number::text
            ),
            'episode',
            pg_temp.gf_migration_uuid('season:' || mi.id::text || ':' || mf.season_number::text),
            mi.library_category,
            'Episode ' || lpad(mf.episode_number::text, 2, '0'),
            'Episode ' || lpad(mf.episode_number::text, 2, '0'),
            mf.season_number,
            mf.episode_number,
            mi.metadata_fetched,
            mi.metadata_fetched_at
        FROM media_items mi
        JOIN media_files mf ON mf.media_item_id = mi.id
        WHERE mi.media_shape = 'series'
          AND mf.season_number IS NOT NULL
          AND mf.episode_number IS NOT NULL
        GROUP BY mi.id, mi.library_category, mf.season_number, mf.episode_number, mi.metadata_fetched, mi.metadata_fetched_at
        """
    )
    op.execute(
        """
        INSERT INTO metadata.provider_identity (
            id,
            entity_id,
            provider_name,
            provider_media_type,
            provider_id,
            primary_identity,
            created_at,
            updated_at
        )
        SELECT
            pg_temp.gf_migration_uuid(
                'provider_identity:' || external_provider || ':' || media_shape || ':' || external_provider_id
            ),
            id,
            external_provider,
            media_shape,
            external_provider_id,
            true,
            created_at,
            updated_at
        FROM media_items
        WHERE external_provider IS NOT NULL
          AND external_provider_id IS NOT NULL
        """
    )
    op.execute(
        """
        INSERT INTO metadata.entity_alias (
            id,
            entity_id,
            alias,
            normalized_alias,
            source,
            is_primary,
            created_at
        )
        SELECT
            pg_temp.gf_migration_uuid('alias:title:' || id::text || ':' || lower(title)),
            id,
            title,
            lower(regexp_replace(title, '\\s+', ' ', 'g')),
            'legacy',
            true,
            created_at
        FROM media_items
        """
    )
    op.execute(
        """
        INSERT INTO metadata.entity_alias (
            id,
            entity_id,
            alias,
            normalized_alias,
            source,
            is_primary,
            created_at
        )
        SELECT
            pg_temp.gf_migration_uuid('alias:original_title:' || id::text || ':' || lower(original_title)),
            id,
            original_title,
            lower(regexp_replace(original_title, '\\s+', ' ', 'g')),
            'legacy',
            false,
            created_at
        FROM media_items
        WHERE original_title IS NOT NULL
          AND original_title <> title
        """
    )
    op.execute(
        """
        INSERT INTO metadata.media_file (
            id,
            entity_id,
            original_path,
            original_filename,
            sanitized_name,
            extension,
            size_bytes,
            season_number,
            episode_number,
            created_at,
            updated_at
        )
        SELECT
            mf.id,
            CASE
                WHEN mi.media_shape = 'series'
                 AND mf.season_number IS NOT NULL
                 AND mf.episode_number IS NOT NULL
                THEN pg_temp.gf_migration_uuid(
                    'episode:' || mi.id::text || ':' || mf.season_number::text || ':' || mf.episode_number::text
                )
                ELSE mf.media_item_id
            END,
            mf.original_path,
            mf.original_filename,
            mf.sanitized_name,
            mf.extension,
            mf.size_bytes,
            mf.season_number,
            mf.episode_number,
            mf.created_at,
            mf.updated_at
        FROM media_files mf
        JOIN media_items mi ON mi.id = mf.media_item_id
        """
    )
    op.execute(
        """
        INSERT INTO metadata.artwork_asset (
            id,
            entity_id,
            artwork_role,
            source,
            source_provider_id,
            stored_path,
            preferred,
            fallback_rank,
            width,
            height,
            created_at,
            updated_at
        )
        SELECT
            id,
            media_item_id,
            image_type,
            source_provider,
            source_provider_id,
            absolute_path,
            true,
            0,
            width,
            height,
            created_at,
            created_at
        FROM media_images
        """
    )
    op.execute(
        """
        INSERT INTO metadata.metadata_evidence (
            id,
            entity_id,
            evidence_type,
            source,
            summary,
            payload
        )
        SELECT
            pg_temp.gf_migration_uuid('legacy_evidence:' || id::text),
            id,
            'legacy_backfill',
            'migration',
            'Backfilled from legacy public media_items table',
            jsonb_build_object(
                'media_item_id', id::text,
                'media_shape', media_shape,
                'external_provider', external_provider,
                'external_provider_id', external_provider_id
            )
        FROM media_items
        """
    )


def downgrade():
    op.execute("DROP TABLE metadata.metadata_issue")
    op.execute("DROP TABLE metadata.metadata_evidence")
    op.execute("DROP TABLE metadata.artwork_asset")
    op.execute("DROP TABLE metadata.media_file")
    op.execute("DROP TABLE metadata.entity_alias")
    op.execute("DROP TABLE metadata.provider_identity")
    op.execute("DROP TABLE metadata.media_entity")
    op.execute("DROP SCHEMA IF EXISTS catalog")
    op.execute("DROP SCHEMA IF EXISTS metadata")
