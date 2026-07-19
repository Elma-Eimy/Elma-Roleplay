"""add memory source start message id

Revision ID: d7e2f3a4b5c6
Revises: c6d1e2f3a4b5
Create Date: 2026-07-18 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7e2f3a4b5c6"
down_revision: Union[str, None] = "c6d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("memory_chunks") as batch_op:
        batch_op.add_column(
            sa.Column("source_start_message_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_memory_chunks_source_start_message_id_chat_messages",
            "chat_messages",
            ["source_start_message_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("memory_chunks") as batch_op:
        batch_op.drop_constraint(
            "fk_memory_chunks_source_start_message_id_chat_messages",
            type_="foreignkey",
        )
        batch_op.drop_column("source_start_message_id")
