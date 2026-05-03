"""provider match candidates"""

from alembic import op


revision = "20260503_0004"
down_revision = "20260503_0003"
branch_labels = None
depends_on = None


def upgrade():
    op.execute(
        """
        CREATE TABLE metadata.provider_match_candidate (
            id uuid PRIMARY KEY,
            metadata_job_id uuid NOT NULL REFERENCES metadata_jobs(id),
            provider_name varchar(64) NOT NULL,
            provider_id varchar(128) NOT NULL,
            provider_media_type varchar(32) NOT NULL,
            title varchar(512) NOT NULL,
            original_title varchar(512),
            release_date date,
            release_year integer,
            popularity double precision,
            provider_rank integer,
            raw_score_components jsonb NOT NULL,
            confidence_score double precision NOT NULL,
            selected boolean NOT NULL DEFAULT false,
            created_at timestamp with time zone NOT NULL DEFAULT now(),
            CONSTRAINT uq_provider_match_candidate_job_provider
                UNIQUE (metadata_job_id, provider_name, provider_media_type, provider_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_provider_match_candidate_job_id ON metadata.provider_match_candidate(metadata_job_id)")
    op.execute("CREATE INDEX ix_provider_match_candidate_score ON metadata.provider_match_candidate(confidence_score)")


def downgrade():
    op.execute("DROP TABLE metadata.provider_match_candidate")
