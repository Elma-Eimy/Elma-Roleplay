"""add session fork message id

Revision ID: c6d1e2f3a4b5
Revises: 7b5f07a213e4
Create Date: 2026-07-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c6d1e2f3a4b5"
down_revision: Union[str, None] = "7b5f07a213e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # SQLite 需要 batch 模式才能为已有表补充外键约束。字段保持 nullable，
    # 不对旧会话做不可靠的内容匹配回填。
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.add_column(sa.Column("fork_message_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_sessions_fork_message_id_chat_messages",
            "chat_messages",
            ["fork_message_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_sessions_fork_message_id",
            ["fork_message_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.drop_index("ix_sessions_fork_message_id")
        batch_op.drop_constraint(
            "fk_sessions_fork_message_id_chat_messages",
            type_="foreignkey",
        )
        batch_op.drop_column("fork_message_id")
