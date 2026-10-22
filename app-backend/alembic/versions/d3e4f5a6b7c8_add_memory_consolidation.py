"""Add reversible story-scoped memory consolidation, preserving existing cards."""

from alembic import op
import sqlalchemy as sa

revision = "d3e4f5a6b7c8"
down_revision = "c2d3e4f5a6b7"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "memory_consolidations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("persona_id", sa.Integer(), sa.ForeignKey("session_personas.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("preview_json", sa.Text(), nullable=False),
        sa.Column("selected_json", sa.Text()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_memory_consolidations_persona_id", "memory_consolidations", ["persona_id"])
    # SQLite 支持添加可空、默认 NULL 的引用列，无需重建有自引用的记忆表。
    op.execute("ALTER TABLE memory_chunks ADD COLUMN consolidation_id INTEGER REFERENCES memory_consolidations(id) ON DELETE CASCADE")
    op.create_index("ix_memory_chunks_consolidation_id", "memory_chunks", ["consolidation_id"])
    op.create_table(
        "memory_consolidation_sources",
        sa.Column("summary_id", sa.Integer(), sa.ForeignKey("memory_chunks.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("memory_chunks.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_table(
        "memory_consolidation_scopes",
        sa.Column("persona_id", sa.Integer(), sa.ForeignKey("session_personas.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("consolidation_id", sa.Integer(), sa.ForeignKey("memory_consolidations.id", ondelete="CASCADE"), primary_key=True),
    )
    op.create_index("ix_memory_consolidation_sources_source_id", "memory_consolidation_sources", ["source_id"])
    op.create_index("ix_memory_consolidation_scopes_consolidation_id", "memory_consolidation_scopes", ["consolidation_id"])


def downgrade():
    op.drop_table("memory_consolidation_scopes")
    op.drop_table("memory_consolidation_sources")
    op.execute("DELETE FROM memory_chunks WHERE consolidation_id IS NOT NULL")
    op.drop_index("ix_memory_chunks_consolidation_id", table_name="memory_chunks")
    op.drop_column("memory_chunks", "consolidation_id")
    op.drop_table("memory_consolidations")
