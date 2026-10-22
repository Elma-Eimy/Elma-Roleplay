"""Keep append-only graph versions with message and memory evidence."""
from alembic import op
import sqlalchemy as sa

revision = "b7c8d9e0f1a2"
down_revision = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("graph_entities", "graph_relations"):
        op.add_column(table, sa.Column("source_start_message_id", sa.Integer(), nullable=True))
        op.add_column(table, sa.Column("source_message_id_bound", sa.Integer(), nullable=True))
        op.add_column(table, sa.Column("evidence_json", sa.Text(), nullable=True))
        op.create_index("ix_" + table + "_persona_source", table, ["persona_id", "source_message_id_bound"])
    op.add_column("graph_entities", sa.Column("is_stub", sa.Boolean(), server_default="0", nullable=False))


def downgrade():
    # 原生 DROP COLUMN 避免重建父表触发 SQLite 外键级联。
    op.drop_column("graph_entities", "is_stub")
    for table in ("graph_relations", "graph_entities"):
        op.drop_index("ix_" + table + "_persona_source", table_name=table)
        for column in ("evidence_json", "source_message_id_bound", "source_start_message_id"):
            op.drop_column(table, column)
