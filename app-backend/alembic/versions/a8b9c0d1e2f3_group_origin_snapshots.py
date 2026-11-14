"""冻结群聊成员的来源状态与继承记忆，不引用可变来源行。"""
from alembic import op
import sqlalchemy as sa

revision = "a8b9c0d1e2f3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "group_persona_origins",
        sa.Column("persona_id", sa.Integer(), sa.ForeignKey("session_personas.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("mode", sa.String(20), nullable=False),
        sa.Column("snapshot_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("initial_state_json", sa.Text(), nullable=False),
        sa.Column("source_session_id", sa.Integer()),
        sa.Column("source_persona_id", sa.Integer()),
        sa.Column("source_last_active_message_id", sa.Integer()),
        sa.Column("source_confirmed_before_id", sa.Integer()),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.CheckConstraint("mode IN ('card', 'single_snapshot')", name="ck_group_origin_mode"),
        sa.CheckConstraint("snapshot_version >= 1", name="ck_group_origin_version"),
    )
    op.create_table(
        "group_inherited_memory_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("persona_id", sa.Integer(), sa.ForeignKey("session_personas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("memory_type", sa.String(20), nullable=False),
        sa.Column("importance_score", sa.Float()),
        sa.Column("temporal_status", sa.String(20), nullable=False),
        sa.Column("temporal_note", sa.String(120)),
        sa.Column("source_evidence_json", sa.Text()),
        sa.Column("source_memory_id", sa.Integer(), nullable=False),
        sa.Column("source_persona_id", sa.Integer(), nullable=False),
        sa.Column("source_session_id", sa.Integer()),
        sa.Column("source_start_message_id", sa.Integer()),
        sa.Column("source_message_id", sa.Integer()),
        sa.Column("source_message_id_bound", sa.Integer()),
        sa.Column("source_created_at", sa.DateTime()),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("content_fingerprint", sa.String(64), nullable=False),
        sa.UniqueConstraint("persona_id", "source_memory_id", name="uq_group_snapshot_source"),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_group_inherited_memory_snapshots_persona_id", "group_inherited_memory_snapshots", ["persona_id"])


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM group_persona_origins LIMIT 1")).first() or connection.execute(
        sa.text("SELECT 1 FROM group_inherited_memory_snapshots LIMIT 1")
    ).first():
        raise RuntimeError("存在群聊来源快照，拒绝丢弃；请先处理相关群聊")
    op.drop_table("group_inherited_memory_snapshots")
    op.drop_table("group_persona_origins")
