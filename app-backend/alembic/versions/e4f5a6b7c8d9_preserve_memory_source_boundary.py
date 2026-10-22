"""Preserve memory source cutoffs independently of deletable message references."""

import json
from alembic import op
import sqlalchemy as sa

revision = "e4f5a6b7c8d9"
down_revision = "d3e4f5a6b7c8"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("memory_chunks", sa.Column("source_message_id_bound", sa.Integer(), nullable=True))
    connection = op.get_bind()
    connection.execute(sa.text("UPDATE memory_chunks SET source_message_id_bound = source_message_id"))

    # 第一版可能已发生来源删除。整理预览保留了不可变消息范围，可用于保守恢复。
    recovered = {}
    for (raw,) in connection.execute(sa.text("SELECT preview_json FROM memory_consolidations")):
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            continue
        sources = payload.get("sources") if isinstance(payload, dict) else None
        if not isinstance(sources, list):
            continue
        for source in sources:
            if not isinstance(source, dict):
                continue
            memory_id, boundary = source.get("id"), source.get("source_message_id")
            if type(memory_id) is int and type(boundary) is int and memory_id > 0 and boundary > 0:
                recovered[memory_id] = max(recovered.get(memory_id, 0), boundary)
    if recovered:
        connection.execute(sa.text(
            "UPDATE memory_chunks SET source_message_id_bound = :boundary "
            "WHERE id = :memory_id AND source_message_id_bound IS NULL"
        ), [{"memory_id": memory_id, "boundary": boundary} for memory_id, boundary in recovered.items()])

    # 整理产物的外键也可能已被置空；从精确来源关联恢复其完整上界。
    summaries = connection.execute(sa.text(
        "SELECT links.summary_id, MAX(source.source_message_id_bound) AS boundary "
        "FROM memory_consolidation_sources links "
        "JOIN memory_chunks source ON source.id = links.source_id "
        "GROUP BY links.summary_id HAVING MAX(source.source_message_id_bound) IS NOT NULL"
    )).all()
    if summaries:
        connection.execute(sa.text(
            "UPDATE memory_chunks SET source_message_id_bound = :boundary WHERE id = :memory_id "
            "AND (source_message_id_bound IS NULL OR source_message_id_bound < :boundary)"
        ), [{"memory_id": row[0], "boundary": row[1]} for row in summaries])


def downgrade():
    op.drop_column("memory_chunks", "source_message_id_bound")
