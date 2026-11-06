"""为 SQLite 会话保留已分配编号，避免删除后旧请求命中新会话。"""
from alembic import op
from sqlalchemy import CheckConstraint, Column, Integer

revision = "b2f3a4b5c6d7"
down_revision = "b1e2f3a4b5c6"
branch_labels = None
depends_on = None


def _rebuild_sessions(autoincrement):
    # SQLite 反射会将列内 CHECK 还原为表级约束。保留原列定义，让前一版本仍可直接删除该列。
    revision_column = Column("group_revision", Integer,
        CheckConstraint("group_revision >= 0", name="ck_group_revision"), nullable=False, server_default="0")
    with op.batch_alter_table("sessions", recreate="always", reflect_args=[revision_column],
                              table_kwargs={"sqlite_autoincrement": autoincrement}) as batch:
        batch.drop_constraint("ck_group_revision", type_="check")


def upgrade():
    _rebuild_sessions(True)


def downgrade():
    _rebuild_sessions(False)
