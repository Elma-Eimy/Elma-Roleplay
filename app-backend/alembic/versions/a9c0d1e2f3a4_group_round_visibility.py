"""群聊轮次、候选、内容和成员知情边界。"""
from alembic import op
import sqlalchemy as sa

revision = "a9c0d1e2f3a4"
down_revision = "a8b9c0d1e2f3"
branch_labels = None
depends_on = None


def upgrade():
    # 仅增加组合外键的目标索引，不重建已有 Session/Persona 表。
    op.create_index("uq_sessions_id_kind", "sessions", ["id", "kind"], unique=True)
    op.create_index("uq_personas_session_id_id", "session_personas", ["session_id", "id"], unique=True)
    op.create_table("group_rounds",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("session_kind", sa.String(10), nullable=False, server_default="group"),
        sa.Column("round_index", sa.Integer(), nullable=False),
        sa.Column("user_content", sa.Text(), nullable=False),
        sa.Column("selected_candidate_id", sa.Integer()),
        sa.Column("confirmed_at", sa.DateTime()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["session_id", "session_kind"], ["sessions.id", "sessions.kind"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["selected_candidate_id", "id", "session_id"],
            ["group_round_candidates.id", "group_round_candidates.round_id", "group_round_candidates.session_id"],
            name="fk_group_round_selected", deferrable=True, initially="DEFERRED"),
        sa.UniqueConstraint("id", "session_id", name="uq_group_round_identity"),
        sa.UniqueConstraint("session_id", "round_index", name="uq_group_round_index"),
        sa.CheckConstraint("session_kind = 'group' AND round_index >= 1", name="ck_group_round_scope"),
        sqlite_autoincrement=True)
    op.create_index("uq_group_round_pending", "group_rounds", ["session_id"], unique=True,
                    sqlite_where=sa.text("confirmed_at IS NULL"))
    op.create_table("group_round_candidates",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("round_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(30), nullable=False, server_default="generating"),
        sa.Column("revision", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_code", sa.String(80)),
        sa.ForeignKeyConstraint(["round_id", "session_id"], ["group_rounds.id", "group_rounds.session_id"], ondelete="CASCADE"),
        sa.UniqueConstraint("id", "round_id", "session_id", name="uq_group_candidate_round"),
        sa.UniqueConstraint("id", "session_id", name="uq_group_candidate_scope"),
        sa.UniqueConstraint("round_id", "version", name="uq_group_candidate_version"),
        sa.CheckConstraint("version >= 1 AND revision >= 0", name="ck_group_candidate_version"),
        sa.CheckConstraint("status IN ('generating', 'awaiting_confirmation', 'failed')", name="ck_group_candidate_status"),
        sqlite_autoincrement=True)
    op.create_table("group_content_items",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("candidate_id", sa.Integer(), nullable=False),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("speaker_persona_id", sa.Integer()),
        sa.Column("content", sa.Text()),
        sa.Column("emotion_tag", sa.String(50)),
        sa.Column("affection_change", sa.Integer()),
        sa.Column("role_state_patch", sa.Text()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["candidate_id", "session_id"], ["group_round_candidates.id", "group_round_candidates.session_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id", "speaker_persona_id"], ["session_personas.session_id", "session_personas.id"], deferrable=True, initially="DEFERRED"),
        sa.UniqueConstraint("id", "session_id", name="uq_group_content_scope"),
        sa.UniqueConstraint("candidate_id", "sequence", name="uq_group_content_sequence"),
        sa.CheckConstraint("(kind = 'user' AND sequence = 0 AND speaker_persona_id IS NULL AND content IS NULL "
            "AND emotion_tag IS NULL AND affection_change IS NULL AND role_state_patch IS NULL) OR "
            "(kind = 'utterance' AND sequence > 0 AND speaker_persona_id IS NOT NULL "
            "AND content IS NOT NULL AND length(trim(content)) > 0)", name="ck_group_content_shape"),
        sa.CheckConstraint("affection_change IS NULL OR affection_change BETWEEN -5 AND 5", name="ck_group_content_affection"),
        sqlite_autoincrement=True)
    op.create_table("group_content_visibility",
        sa.Column("item_id", sa.Integer(), primary_key=True),
        sa.Column("recipient_persona_id", sa.Integer(), primary_key=True),
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("decision", sa.String(10), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(["item_id", "session_id"], ["group_content_items.id", "group_content_items.session_id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["session_id", "recipient_persona_id"], ["session_personas.session_id", "session_personas.id"], deferrable=True, initially="DEFERRED"),
        sa.CheckConstraint("decision IN ('visible', 'hidden') AND policy_version >= 1", name="ck_group_visibility_decision"))
    op.create_index("ix_group_visibility_recipient", "group_content_visibility", ["recipient_persona_id", "decision", "item_id"])


def downgrade():
    if op.get_bind().execute(sa.text("SELECT 1 FROM group_rounds LIMIT 1")).first():
        raise RuntimeError("存在群聊轮次，拒绝丢弃；请先处理相关群聊")
    # Alembic 在线环境在同一事务暂停外键并校验，循环引用的空表可逆序移除。
    for name in ("group_content_visibility", "group_content_items", "group_round_candidates", "group_rounds"):
        op.drop_table(name)
    op.drop_index("uq_personas_session_id_id", table_name="session_personas")
    op.drop_index("uq_sessions_id_kind", table_name="sessions")
