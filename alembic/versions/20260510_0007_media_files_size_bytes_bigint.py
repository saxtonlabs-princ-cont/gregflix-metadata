"""make legacy media file size bigint"""

from alembic import op


revision = "20260510_0007"
down_revision = "20260503_0006"
branch_labels = None
depends_on = None


def upgrade():
    op.execute("ALTER TABLE media_files ALTER COLUMN size_bytes TYPE bigint")


def downgrade():
    op.execute("ALTER TABLE media_files ALTER COLUMN size_bytes TYPE integer")
