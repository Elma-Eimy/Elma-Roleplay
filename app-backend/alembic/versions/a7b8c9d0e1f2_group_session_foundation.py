"""群聊容器与多成员位置；保持旧单聊 ID 和全部引用。"""
from alembic import op
import sqlalchemy as sa

revision = "a7b8c9d0e1f2"
down_revision = "a5b6c7d8e9f0"
branch_labels = None
depends_on = None

NAMING = {"uq": "uq_%(table_name)s_%(column_0_name)s"}


def upgrade():
    with op.batch_alter_table("sessions") as batch:
        batch.add_column(sa.Column("kind", sa.String(10), nullable=False, server_default="single"))
        batch.add_column(sa.Column("shared_setting", sa.Text(), nullable=True))
        batch.add_column(sa.Column("user_nickname", sa.String(50), nullable=True))
        batch.create_check_constraint("ck_sessions_kind", "kind IN ('single', 'group')")
    with op.batch_alter_table("session_personas", naming_convention=NAMING) as batch:
        batch.add_column(sa.Column("member_slot", sa.Integer(), nullable=False, server_default="0"))
        batch.drop_constraint("uq_session_personas_session_id", type_="unique")
        batch.create_unique_constraint("uq_personas_session_slot", ["session_id", "member_slot"])
        batch.create_unique_constraint("uq_personas_session_character", ["session_id", "character_id"])
        batch.create_check_constraint("ck_personas_member_slot", "member_slot BETWEEN 0 AND 3")


def downgrade():
    connection = op.get_bind()
    if connection.execute(sa.text("SELECT 1 FROM sessions WHERE kind = 'group' LIMIT 1")).first():
        raise RuntimeError("存在群聊数据，拒绝降级；请先处理群聊")
    if connection.execute(sa.text(
        "SELECT session_id FROM session_personas GROUP BY session_id "
        "HAVING COUNT(*) > 1 OR MIN(member_slot) != 0 LIMIT 1"
    )).first():
        raise RuntimeError("单聊人格不满足唯一 slot 0，拒绝降级")
    with op.batch_alter_table("session_personas", naming_convention=NAMING) as batch:
        batch.drop_constraint("ck_personas_member_slot", type_="check")
        batch.drop_constraint("uq_personas_session_slot", type_="unique")
        batch.drop_constraint("uq_personas_session_character", type_="unique")
        batch.drop_column("member_slot")
        batch.create_unique_constraint("uq_session_personas_session_id", ["session_id"])
    with op.batch_alter_table("sessions") as batch:
        batch.drop_constraint("ck_sessions_kind", type_="check")
        batch.drop_column("user_nickname")
        batch.drop_column("shared_setting")
        batch.drop_column("kind")
