"""Persist extracted candidates independently of model and index availability."""
from alembic import op
import sqlalchemy as sa
import json

revision = "a3b4c5d6e7f8"
down_revision = "a2b3c4d5e6f7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "memory_extraction_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("persona_id", sa.Integer(), sa.ForeignKey("session_personas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("dedupe_key", sa.String(80), nullable=True, unique=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("payload_json", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_after", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("lease_until", sa.DateTime(), nullable=True),
        sa.Column("lease_token", sa.String(40), nullable=True),
        sa.Column("last_error_code", sa.String(80), nullable=True),
        sa.Column("written_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sqlite_autoincrement=True,
    )
    op.create_index("ix_memory_extraction_jobs_persona_id", "memory_extraction_jobs", ["persona_id"])
    op.create_index("ix_memory_extraction_jobs_status", "memory_extraction_jobs", ["status"])
    op.create_index("uq_memory_job_processing_persona", "memory_extraction_jobs", ["persona_id"],
                    unique=True, sqlite_where=sa.text("status = 'processing'"))


def downgrade():
    connection = op.get_bind()
    # Old code treats this cursor as fully committed; rewind only stories with outstanding candidates.
    rows = connection.execute(sa.text(
        "SELECT persona_id,payload_json FROM memory_extraction_jobs WHERE kind='candidates' "
        "AND status IN ('pending','processing','retrying')")).all()
    starts = {}
    for persona_id, raw in rows:
        try:
            ids = [source["id"] for source in json.loads(raw).get("sources", []) if type(source.get("id")) is int]
            start = min(ids) if ids else 0
        except (TypeError, ValueError, KeyError):
            start = 0
        starts[persona_id] = min(starts.get(persona_id, start), start)
    for persona_id, start in starts.items():
        previous = connection.execute(sa.text(
            "SELECT max(id) FROM chat_messages WHERE session_id=(SELECT session_id FROM session_personas WHERE id=:pid) "
            "AND id < :start AND is_active=1 AND role IN ('user','assistant')"), {"pid": persona_id, "start": start}).scalar()
        connection.execute(sa.text(
            "UPDATE session_personas SET last_summarized_msg_id=:previous WHERE id=:pid "
            "AND last_summarized_msg_id IS NOT NULL AND last_summarized_msg_id >= :start"),
            {"pid": persona_id, "start": start, "previous": previous})
    op.drop_table("memory_extraction_jobs")
