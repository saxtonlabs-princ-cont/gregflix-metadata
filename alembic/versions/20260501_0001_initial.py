"""initial metadata schema"""

from alembic import op


revision = "20260501_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE media_items (
            id uuid PRIMARY KEY,
            media_shape varchar(32) NOT NULL,
            library_category varchar(32) NOT NULL,
            title varchar(512) NOT NULL,
            sort_title varchar(512) NOT NULL,
            original_title varchar(512),
            overview text,
            release_date date,
            release_year integer,
            runtime_minutes integer,
            parent_id uuid REFERENCES media_items(id),
            season_number integer,
            episode_number integer,
            external_provider varchar(64),
            external_provider_id varchar(128),
            external_imdb_id varchar(64),
            metadata_fetched boolean NOT NULL DEFAULT false,
            metadata_fetched_at timestamp with time zone,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now(),
            CONSTRAINT uq_media_items_provider_shape
                UNIQUE (external_provider, external_provider_id, media_shape)
        )
        """
    )
    op.execute(
        """
        CREATE TABLE metadata_jobs (
            id uuid PRIMARY KEY,
            status varchar(32) NOT NULL,
            folder_path varchar(2048) NOT NULL,
            library_name varchar(255) NOT NULL,
            library_category varchar(32) NOT NULL,
            media_shape varchar(32),
            started_at timestamp with time zone,
            finished_at timestamp with time zone,
            error text,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE media_files (
            id uuid PRIMARY KEY,
            media_item_id uuid NOT NULL REFERENCES media_items(id),
            original_path varchar(2048) NOT NULL UNIQUE,
            original_filename varchar(512) NOT NULL,
            sanitized_name varchar(512) NOT NULL,
            extension varchar(32) NOT NULL,
            size_bytes integer,
            season_number integer,
            episode_number integer,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            updated_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        """
        CREATE TABLE media_images (
            id uuid PRIMARY KEY,
            media_item_id uuid NOT NULL REFERENCES media_items(id),
            image_type varchar(32) NOT NULL,
            absolute_path varchar(2048) NOT NULL UNIQUE,
            source_provider varchar(64) NOT NULL,
            source_provider_id varchar(128),
            width integer,
            height integer,
            created_at timestamp with time zone NOT NULL DEFAULT now()
        )
        """
    )


def downgrade():
    op.execute("DROP TABLE media_images")
    op.execute("DROP TABLE media_files")
    op.execute("DROP TABLE metadata_jobs")
    op.execute("DROP TABLE media_items")
