"""add memory navigation indexes"""

from typing import Sequence, Union

from alembic import op


revision: str = "b1c2d3e4f5a6"
down_revision: Union[str, None] = "a9b8c7d6e5f4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, None] = None


def upgrade() -> None:
    op.execute(
        "CREATE INDEX ix_memory_chunks_persona_created_id "
        "ON memory_chunks (persona_id, created_at DESC, id DESC)"
    )
    op.execute(
        "CREATE INDEX ix_chat_messages_session_active_created_id "
        "ON chat_messages (session_id, is_active, created_at DESC, id DESC)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX ix_chat_messages_session_active_created_id")
    op.execute("DROP INDEX ix_memory_chunks_persona_created_id")
