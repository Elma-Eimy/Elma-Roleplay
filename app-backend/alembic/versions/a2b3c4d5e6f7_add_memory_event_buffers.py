"""Persist branch-local ongoing events before long-term admission."""
from alembic import op
import sqlalchemy as sa

revision = "a2b3c4d5e6f7"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "memory_event_buffers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("persona_id", sa.Integer(), sa.ForeignKey("session_personas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("age_batches", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_memory_event_buffers_persona_id", "memory_event_buffers", ["persona_id"])


def downgrade():
    op.drop_table("memory_event_buffers")
