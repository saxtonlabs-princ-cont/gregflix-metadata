"""initial schema"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260501_0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "media_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("media_shape", sa.String(length=32), nullable=False),
        sa.Column("library_category", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=False),
        sa.Column("sort_title", sa.String(length=512), nullable=False),
        sa.Column("original_title", sa.String(length=512), nullable=True),
        sa.Column("overview", sa.Text(), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column("release_year", sa.Integer(), nullable=True),
        sa.Column("runtime_minutes", sa.Integer(), nullable=True),
        sa.Column("parent_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("media_items.id"), nullable=True),
        sa.Column("season_number", sa.Integer(), nullable=True),
        sa.Column("episode_number", sa.Integer(), nullable=True),
        sa.Column("external_provider", sa.String(length=64), nullable=True),
        sa.Column("external_provider_id", sa.String(length=128), nullable=True),
        sa.Column("external_imdb_id", sa.String(length=64), nullable=True),
        sa.Column("metadata_fetched", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("metadata_fetched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("external_provider", "external_provider_id", "media_shape", name="uq_media_items_provider_shape"),
    )
    op.create_table(
        "metadata_jobs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("folder_path", sa.String(length=2048), nullable=False),
        sa.Column("library_name", sa.String(length=255), nullable=False),
        sa.Column("library_category", sa.String(length=32), nullable=False),
        sa.Column("media_shape", sa.String(length=32), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "media_files",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("media_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("media_items.id"), nullable=False),
        sa.Column("original_path", sa.String(length=2048), nullable=False),
        sa.Column("original_filename", sa.String(length=512), nullable=False),
        sa.Column("sanitized_name", sa.String(length=512), nullable=False),
        sa.Column("extension", sa.String(length=32), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("season_number", sa.Integer(), nullable=True),
        sa.Column("episode_number", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("original_path"),
    )
    op.create_table(
        "media_images",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("media_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("media_items.id"), nullable=False),
        sa.Column("image_type", sa.String(length=32), nullable=False),
        sa.Column("absolute_path", sa.String(length=2048), nullable=False),
        sa.Column("source_provider", sa.String(length=64), nullable=False),
        sa.Column("source_provider_id", sa.String(length=128), nullable=True),
        sa.Column("width", sa.Integer(), nullable=True),
        sa.Column("height", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("absolute_path"),
    )


def downgrade():
    op.drop_table("media_images")
    op.drop_table("media_files")
    op.drop_table("metadata_jobs")
    op.drop_table("media_items")
