"""add session fork message id"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c6d1e2f3a4b5"
down_revision: Union[str, None] = "7b5f07a213e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Never batch-recreate this parent table on SQLite: with foreign_keys=ON,
    # dropping sessions cascades into session_personas and chat_messages.
    op.execute(
        "ALTER TABLE sessions ADD COLUMN fork_message_id INTEGER "
        "REFERENCES chat_messages(id) ON DELETE SET NULL"
    )
    op.create_index("ix_sessions_fork_message_id", "sessions", ["fork_message_id"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table("sessions") as batch_op:
        batch_op.drop_index("ix_sessions_fork_message_id")
        batch_op.drop_constraint(
            "fk_sessions_fork_message_id_chat_messages", type_="foreignkey"
        )
        batch_op.drop_column("fork_message_id")
