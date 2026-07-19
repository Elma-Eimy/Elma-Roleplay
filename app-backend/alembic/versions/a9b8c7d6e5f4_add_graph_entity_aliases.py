"""add graph entity aliases

Revision ID: a9b8c7d6e5f4
Revises: f8a3b4c5d6e7
Create Date: 2026-07-19 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, None] = "f8a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("graph_entities") as batch_op:
        batch_op.add_column(sa.Column("aliases", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("graph_entities") as batch_op:
        batch_op.drop_column("aliases")
