"""保存成员对已确认事件的认识和定向关系。"""
from alembic import op
import sqlalchemy as sa

revision = "b4c5d6e7f8a9"
down_revision = "b3a4b5c6d7e8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("group_round_candidates", sa.Column("insight_watermark", sa.Integer))
    op.create_table("group_member_insights",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("capture_id", sa.Integer, sa.ForeignKey("group_memory_captures.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(12), nullable=False),
        sa.Column("target_persona_id", sa.Integer, sa.ForeignKey("session_personas.id", ondelete="CASCADE")),
        sa.Column("content", sa.Text, nullable=False),
        sa.Column("ref", sa.String(64), nullable=False),
        sa.Column("quote", sa.Text, nullable=False),
        sa.CheckConstraint("kind IN ('cognition','user','member')", name="ck_group_insight_kind"),
        sa.CheckConstraint("(kind = 'member') = (target_persona_id IS NOT NULL)", name="ck_group_insight_target"),
        sqlite_autoincrement=True)
    op.create_index("ix_group_member_insights_capture_id", "group_member_insights", ["capture_id"])


def downgrade():
    if op.get_bind().exec_driver_sql("SELECT 1 FROM group_member_insights LIMIT 1").first():
        raise RuntimeError("群聊已有成员认知，拒绝有损降级")
    op.drop_table("group_member_insights")
    op.drop_column("group_round_candidates", "insight_watermark")
