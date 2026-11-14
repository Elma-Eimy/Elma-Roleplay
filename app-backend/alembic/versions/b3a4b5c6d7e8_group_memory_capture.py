"""保存群聊已确认轮次的成员提纯任务与带证据结果。"""
from alembic import op
import sqlalchemy as sa

revision = "b3a4b5c6d7e8"
down_revision = "b2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("group_memory_captures",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("session_id", sa.Integer, nullable=False),
        sa.Column("round_id", sa.Integer, nullable=False),
        sa.Column("candidate_id", sa.Integer, nullable=False),
        sa.Column("persona_id", sa.Integer, nullable=False),
        sa.Column("attempts", sa.Integer, nullable=False, server_default="0"),
        sa.Column("run_after", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("error_code", sa.String(40)),
        sa.Column("cards_json", sa.Text),
        sa.ForeignKeyConstraint(["candidate_id", "round_id", "session_id"],
            ["group_round_candidates.id", "group_round_candidates.round_id", "group_round_candidates.session_id"],
            ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id", "persona_id"], ["session_personas.session_id", "session_personas.id"],
            ondelete="CASCADE"),
        sa.UniqueConstraint("round_id", "persona_id", name="uq_group_capture_recipient"),
        sqlite_autoincrement=True)
    op.create_index("ix_group_capture_due", "group_memory_captures", ["run_after"],
                    sqlite_where=sa.text("cards_json IS NULL"))


def downgrade():
    if op.get_bind().exec_driver_sql("SELECT 1 FROM group_memory_captures LIMIT 1").first():
        raise RuntimeError("群聊提纯已有任务或结果，拒绝有损降级")
    op.drop_table("group_memory_captures")
