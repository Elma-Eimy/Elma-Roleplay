"""Keep event identities across bounded checkpoints."""
from alembic import op
import sqlalchemy as sa

revision = "a4b5c6d7e8f9"
down_revision = "a3b4c5d6e7f8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("memory_event_buffers", sa.Column("status", sa.String(20), nullable=False, server_default="open"))
    op.create_index("ix_memory_event_buffers_status", "memory_event_buffers", ["status"])
    # Inline nullable REFERENCES avoids rebuilding a table referenced by graph evidence.
    op.execute("ALTER TABLE memory_chunks ADD COLUMN event_id INTEGER REFERENCES memory_event_buffers(id) ON DELETE SET NULL")
    op.create_index("ix_memory_chunks_event_id", "memory_chunks", ["event_id"])


def downgrade():
    # Older code must not promote an empty checkpoint again.
    op.execute("DELETE FROM memory_event_buffers WHERE status != 'open'")
    op.drop_index("ix_memory_chunks_event_id", table_name="memory_chunks")
    op.drop_column("memory_chunks", "event_id")
    op.drop_index("ix_memory_event_buffers_status", table_name="memory_event_buffers")
    op.drop_column("memory_event_buffers", "status")
