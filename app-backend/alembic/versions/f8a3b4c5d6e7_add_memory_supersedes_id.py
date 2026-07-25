"""add memory supersedes id"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f8a3b4c5d6e7"
down_revision: Union[str, None] = "d7e2f3a4b5c6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE memory_chunks ADD COLUMN supersedes_id INTEGER "
        "REFERENCES memory_chunks(id) ON DELETE SET NULL"
    )
    op.create_index("ix_memory_chunks_supersedes_id", "memory_chunks", ["supersedes_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("memory_chunks") as batch_op:
        batch_op.drop_index("ix_memory_chunks_supersedes_id")
        batch_op.drop_constraint(
            "fk_memory_chunks_supersedes_id_memory_chunks", type_="foreignkey"
        )
        batch_op.drop_column("supersedes_id")
