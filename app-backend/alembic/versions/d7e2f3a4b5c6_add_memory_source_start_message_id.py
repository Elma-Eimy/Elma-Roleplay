"""add memory source start message id"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d7e2f3a4b5c6"
down_revision: Union[str, None] = "c6d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "ALTER TABLE memory_chunks ADD COLUMN source_start_message_id INTEGER "
        "REFERENCES chat_messages(id) ON DELETE SET NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("memory_chunks") as batch_op:
        batch_op.drop_constraint(
            "fk_memory_chunks_source_start_message_id_chat_messages", type_="foreignkey"
        )
        batch_op.drop_column("source_start_message_id")
