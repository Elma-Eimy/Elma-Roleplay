"""保存不可变的原文事实片段，既有卡片保持原样。"""
from alembic import op
import sqlalchemy as sa
from core.group_recall_schema_v2 import TRIGGER, install_parts_trigger

revision = 'b6e7f8a9b0c1'
down_revision = 'b5d6e7f8a9b0'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('group_recall_cards', sa.Column('parts_json', sa.Text(), nullable=True))
    install_parts_trigger(op.get_bind())


def downgrade():
    db = op.get_bind()
    if (db.exec_driver_sql('SELECT 1 FROM group_recall_cards WHERE parts_json IS NOT NULL LIMIT 1').first()
            or db.exec_driver_sql("SELECT 1 FROM group_round_candidates WHERE json_extract(call_snapshot_json,'$.fact_recall')=1 LIMIT 1").first()
            or db.exec_driver_sql("SELECT 1 FROM group_memory_captures WHERE EXISTS (SELECT 1 FROM json_each(cards_json) WHERE json_extract(value,'$.claim_kind') IS NOT NULL) LIMIT 1").first()):
        raise RuntimeError('仍有分段记忆或新版候选，拒绝有损降级')
    op.execute(f'DROP TRIGGER {TRIGGER}')
    op.drop_column('group_recall_cards', 'parts_json')
