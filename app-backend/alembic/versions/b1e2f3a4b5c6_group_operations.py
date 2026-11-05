"""M4-A 持久操作回执与会话版本；不重建历史表。"""
from alembic import op
from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKeyConstraint, UniqueConstraint, CheckConstraint, text, func

revision = "b1e2f3a4b5c6"
down_revision = "b0d1e2f3a4b5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sessions", Column("group_revision", Integer, CheckConstraint("group_revision >= 0", name="ck_group_revision"), nullable=False, server_default="0"))
    op.add_column("group_rounds", Column("discarded_at", DateTime, CheckConstraint("discarded_at IS NULL OR confirmed_at IS NULL", name="ck_group_round_discard")))
    op.drop_index("uq_group_round_pending", table_name="group_rounds")
    op.create_index("uq_group_round_pending", "group_rounds", ["session_id"], unique=True, sqlite_where=text("confirmed_at IS NULL AND discarded_at IS NULL"))
    op.add_column("group_round_candidates", Column("checkpoint", String(30), CheckConstraint("checkpoint IN ('user_visibility', 'next_action', 'role_generation', 'finish', 'done')", name="ck_group_checkpoint")))
    op.add_column("group_round_candidates", Column("call_snapshot_json", Text))
    op.add_column("group_round_candidates", Column("provider_fingerprint", String(64)))
    op.create_table("group_round_operations",
        Column('id', Integer, primary_key=True),
        Column('session_id', Integer, nullable=False),
        Column('round_id', Integer, nullable=False),
        Column('candidate_id', Integer, nullable=False),
        Column('client_request_id', String(36), nullable=False),
        Column('kind', String(20), nullable=False),
        Column('status', String(20), nullable=False),
        Column('revision', Integer, nullable=False, default=0, server_default="0"),
        Column('request_fingerprint', String(64), nullable=False),
        Column('accepted_result_json', Text, nullable=False),
        Column('call_count', Integer, nullable=False, default=0, server_default="0"),
        Column('call_limit', Integer, nullable=False, default=0, server_default="0"),
        Column('created_at', DateTime, nullable=False, server_default=func.now()),
        Column('started_at', DateTime),
        Column('deadline_at', DateTime),
        Column('finished_at', DateTime),
        Column('error_code', String(80)),

        ForeignKeyConstraint(["round_id", "session_id"], ["group_rounds.id", "group_rounds.session_id"], ondelete="CASCADE"),
        ForeignKeyConstraint(["candidate_id", "round_id", "session_id"],
            ["group_round_candidates.id", "group_round_candidates.round_id", "group_round_candidates.session_id"], ondelete="CASCADE"),
        UniqueConstraint("session_id", "client_request_id", name="uq_group_operation_request"),
        CheckConstraint("kind IN ('send', 'regenerate', 'resume', 'select', 'discard')", name="ck_group_operation_kind"),
        CheckConstraint("status IN ('queued', 'running', 'succeeded', 'failed')", name="ck_group_operation_status"),
        CheckConstraint("revision >= 0 AND call_count >= 0 AND call_limit >= 0", name="ck_group_operation_counters"),

        sqlite_autoincrement=True)
    op.create_index("uq_group_operation_active", "group_round_operations", ["session_id"], unique=True, sqlite_where=text("status IN ('queued', 'running')"))


def downgrade():
    bind = op.get_bind()
    for query in (
        "SELECT 1 FROM sessions WHERE group_revision != 0 LIMIT 1",
        "SELECT 1 FROM group_rounds WHERE discarded_at IS NOT NULL LIMIT 1",
        "SELECT 1 FROM group_round_candidates WHERE checkpoint IS NOT NULL OR call_snapshot_json IS NOT NULL OR provider_fingerprint IS NOT NULL LIMIT 1",
        "SELECT 1 FROM group_round_operations LIMIT 1",
    ):
        if bind.execute(text(query)).first():
            raise RuntimeError("存在 M4 操作数据，拒绝有损降级")
    op.drop_table("group_round_operations")
    for name in ("provider_fingerprint", "call_snapshot_json", "checkpoint"):
        op.drop_column("group_round_candidates", name)
    op.drop_index("uq_group_round_pending", table_name="group_rounds")
    op.drop_column("group_rounds", "discarded_at")
    op.create_index("uq_group_round_pending", "group_rounds", ["session_id"], unique=True, sqlite_where=text("confirmed_at IS NULL"))
    op.drop_column("sessions", "group_revision")
