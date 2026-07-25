"""add graph entity aliases"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a9b8c7d6e5f4"
down_revision: Union[str, None] = "f8a3b4c5d6e7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    # graph_relations cascades when referenced graph_entities are dropped.
    op.add_column("graph_entities", sa.Column("aliases", sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("graph_entities") as batch_op:
        batch_op.drop_column("aliases")
