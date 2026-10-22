"""Track successful consolidation scans independently of application state."""

from alembic import op
import sqlalchemy as sa

revision = "f5a6b7c8d9e0"
down_revision = "e4f5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade():
    # 旧预览保留原样；首次使用增量扫描时从未检查开始，不猜测旧扫描进度。
    op.create_table(
        "memory_consolidation_scans",
        sa.Column("persona_id", sa.Integer(), sa.ForeignKey("session_personas.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("memory_id", sa.Integer(), sa.ForeignKey("memory_chunks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("fingerprint", sa.String(64), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_memory_consolidation_scans_memory_id", "memory_consolidation_scans", ["memory_id"])


def downgrade():
    op.drop_table("memory_consolidation_scans")
