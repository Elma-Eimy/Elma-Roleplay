"""Record successful memory job completion times without guessing old timestamps."""
from alembic import op
import sqlalchemy as sa

revision = "a5b6c7d8e9f0"
down_revision = "a4b5c6d7e8f9"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("memory_extraction_jobs", sa.Column("completed_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("memory_extraction_jobs", "completed_at")
