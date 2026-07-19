"""add memory supersedes id

Revision ID: f8a3b4c5d6e7
Revises: d7e2f3a4b5c6
Create Date: 2026-07-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8a3b4c5d6e7"
down_revision: Union[str, None] = "d7e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("memory_chunks") as batch_op:
        batch_op.add_column(
            sa.Column("supersedes_id", sa.Integer(), nullable=True)
        )
        batch_op.create_foreign_key(
            "fk_memory_chunks_supersedes_id_memory_chunks",
            "memory_chunks",
            ["supersedes_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index(
            "ix_memory_chunks_supersedes_id",
            ["supersedes_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("memory_chunks") as batch_op:
        batch_op.drop_index("ix_memory_chunks_supersedes_id")
        batch_op.drop_constraint(
            "fk_memory_chunks_supersedes_id_memory_chunks",
            type_="foreignkey",
        )
        batch_op.drop_column("supersedes_id")
