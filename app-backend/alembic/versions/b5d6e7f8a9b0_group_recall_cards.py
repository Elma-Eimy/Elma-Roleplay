"""为旧快照和已完成的成员提纯分配稳定索引编号。"""
from alembic import op
import sqlalchemy as sa

from core.group_recall_schema_v1 import CAPTURE_INSERT, SNAPSHOT_INSERT, TRIGGERS, install_triggers

revision = "b5d6e7f8a9b0"
down_revision = "b4c5d6e7f8a9"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table("group_recall_cards",
        sa.Column("id", sa.Integer, primary_key=True),
        sa.Column("persona_id", sa.Integer, sa.ForeignKey("session_personas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("snapshot_id", sa.Integer, sa.ForeignKey("group_inherited_memory_snapshots.id", ondelete="CASCADE"), unique=True),
        sa.Column("capture_id", sa.Integer, sa.ForeignKey("group_memory_captures.id", ondelete="CASCADE")),
        sa.Column("slot", sa.Integer),
        sa.Column("replaces_id", sa.Integer),
        sa.Column("indexed", sa.Boolean, nullable=False, server_default="0"),
        sa.CheckConstraint("(snapshot_id IS NOT NULL AND capture_id IS NULL AND slot IS NULL) OR "
                           "(snapshot_id IS NULL AND capture_id IS NOT NULL AND slot IS NOT NULL AND slot >= 0)",
                           name="ck_group_recall_origin"),
        sa.UniqueConstraint("capture_id", "slot", name="uq_group_recall_capture_slot"),
        sqlite_autoincrement=True)
    op.create_index("ix_group_recall_owner", "group_recall_cards", ["persona_id", "id"])
    op.create_index("ix_group_recall_replaces", "group_recall_cards", ["replaces_id"],
                    sqlite_where=sa.text("replaces_id IS NOT NULL"))
    install_triggers(op.get_bind())
    op.execute(SNAPSHOT_INSERT)
    op.execute(CAPTURE_INSERT)


def downgrade():
    db = op.get_bind()
    if db.exec_driver_sql("SELECT 1 FROM group_round_candidates WHERE json_extract(call_snapshot_json,'$.group_card_limit') "
                          "IS NOT NULL LIMIT 1").first() or db.exec_driver_sql("SELECT 1 FROM group_recall_cards LIMIT 1").first() or db.exec_driver_sql(
        "SELECT 1 FROM outbox_jobs WHERE task_type IN ('sync_group_card','rebuild_group_index') LIMIT 1").first():
        raise RuntimeError("群聊仍有召回记录或索引任务，拒绝降级")
    for name in TRIGGERS:
        op.execute(f"DROP TRIGGER {name}")
    op.drop_table("group_recall_cards")
