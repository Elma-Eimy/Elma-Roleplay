"""冻结群聊原卡成员的公开开场，旧群聊保持无开场。"""
from alembic import op
import sqlalchemy as sa

revision = 'b8a9b0c1d2e3'
down_revision = 'b7f8a9b0c1d2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('group_persona_origins', sa.Column('greeting_content', sa.Text(), nullable=True))


def downgrade():
    if op.get_bind().exec_driver_sql(
            'SELECT 1 FROM group_persona_origins WHERE greeting_content IS NOT NULL LIMIT 1').first():
        raise RuntimeError('仍有群聊开场快照，拒绝有损降级')
    op.drop_column('group_persona_origins', 'greeting_content')
