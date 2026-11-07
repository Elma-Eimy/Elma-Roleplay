"""为群聊候选保存独立的成员立绘选择，旧候选不回填。"""
from alembic import op
import sqlalchemy as sa

revision = 'b7f8a9b0c1d2'
down_revision = 'b6e7f8a9b0c1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('group_round_candidates', sa.Column('portrait_selections_json', sa.Text(), nullable=True))


def downgrade():
    if op.get_bind().exec_driver_sql(
            'SELECT 1 FROM group_round_candidates WHERE portrait_selections_json IS NOT NULL LIMIT 1').first():
        raise RuntimeError('仍有群聊候选立绘快照，拒绝有损降级')
    op.drop_column('group_round_candidates', 'portrait_selections_json')
