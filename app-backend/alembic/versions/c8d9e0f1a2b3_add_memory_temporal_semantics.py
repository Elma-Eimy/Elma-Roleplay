"""Preserve story-time semantics on the shared memory fact record."""
from alembic import op
import sqlalchemy as sa

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("memory_chunks", sa.Column("temporal_status", sa.String(20),
                                            nullable=False, server_default="unknown"))
    op.add_column("memory_chunks", sa.Column("temporal_note", sa.String(120), nullable=True))
    op.add_column("memory_chunks", sa.Column("source_evidence_json", sa.Text(), nullable=True))


def downgrade():
    op.drop_column("memory_chunks", "source_evidence_json")
    op.drop_column("memory_chunks", "temporal_note")
    op.drop_column("memory_chunks", "temporal_status")
