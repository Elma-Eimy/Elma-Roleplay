"""保存单聊上下文压缩版本及分支基线。"""

from alembic import op
import sqlalchemy as sa

revision = "c0d1e2f3a4b5"
down_revision = "b9b0c1d2e3f4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("session_personas", sa.Column("context_base", sa.Text(), nullable=True))
    op.create_table(
        "context_checkpoints",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), sa.ForeignKey("sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_count", sa.Integer(), nullable=False),
        sa.Column("source_hash", sa.String(64), nullable=False),
        sa.Column("source_message_id", sa.Integer(), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("session_id", "source_count", "source_hash", name="uq_context_checkpoint_source"),
        sa.CheckConstraint("source_count > 0", name="ck_context_checkpoint_count"),
    )
    op.create_index("ix_context_checkpoints_session_id", "context_checkpoints", ["session_id"])


def downgrade():
    op.drop_table("context_checkpoints")
    op.drop_column("session_personas", "context_base")
