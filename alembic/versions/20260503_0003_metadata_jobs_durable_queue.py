"""metadata jobs durable queue"""

from alembic import op


revision = "20260503_0003"
down_revision = "20260503_0002"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("UPDATE metadata_jobs SET status = 'pending' WHERE status = 'queued'")
    op.execute("ALTER TABLE metadata_jobs ADD COLUMN job_type varchar(64) NOT NULL DEFAULT 'metadata_ingest'")
    op.execute("ALTER TABLE metadata_jobs ADD COLUMN requester varchar(128) NOT NULL DEFAULT 'scanner'")
    op.execute("ALTER TABLE metadata_jobs ADD COLUMN lock_key varchar(2048)")
    op.execute("ALTER TABLE metadata_jobs ADD COLUMN retry_count integer NOT NULL DEFAULT 0")
    op.execute("ALTER TABLE metadata_jobs ADD COLUMN error_stage varchar(128)")
    op.execute("ALTER TABLE metadata_jobs ADD COLUMN error_reason text")
    op.execute("ALTER TABLE metadata_jobs ADD COLUMN claimed_at timestamp with time zone")
    op.execute("ALTER TABLE metadata_jobs ADD COLUMN stale_detected_at timestamp with time zone")
    op.execute("UPDATE metadata_jobs SET lock_key = folder_path WHERE lock_key IS NULL")
    op.execute("ALTER TABLE metadata_jobs ALTER COLUMN lock_key SET NOT NULL")
    op.execute("CREATE INDEX ix_metadata_jobs_status_created_at ON metadata_jobs(status, created_at)")
    op.execute("CREATE INDEX ix_metadata_jobs_lock_key ON metadata_jobs(lock_key)")
    op.execute(
        """
        CREATE UNIQUE INDEX uq_metadata_jobs_active_lock_key
        ON metadata_jobs(lock_key)
        WHERE status IN ('pending', 'running')
        """
    )


def downgrade():
    op.execute("DROP INDEX uq_metadata_jobs_active_lock_key")
    op.execute("DROP INDEX ix_metadata_jobs_lock_key")
    op.execute("DROP INDEX ix_metadata_jobs_status_created_at")
    op.execute("UPDATE metadata_jobs SET status = 'queued' WHERE status = 'pending'")
    op.execute("ALTER TABLE metadata_jobs DROP COLUMN stale_detected_at")
    op.execute("ALTER TABLE metadata_jobs DROP COLUMN claimed_at")
    op.execute("ALTER TABLE metadata_jobs DROP COLUMN error_reason")
    op.execute("ALTER TABLE metadata_jobs DROP COLUMN error_stage")
    op.execute("ALTER TABLE metadata_jobs DROP COLUMN retry_count")
    op.execute("ALTER TABLE metadata_jobs DROP COLUMN lock_key")
    op.execute("ALTER TABLE metadata_jobs DROP COLUMN requester")
    op.execute("ALTER TABLE metadata_jobs DROP COLUMN job_type")
