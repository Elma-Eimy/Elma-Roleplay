"""为重复素材识别保存内容摘要，旧资源按需计算。"""
from alembic import op
import sqlalchemy as sa

revision = 'f1a2b3c4d5e6'
down_revision = 'e0f1a2b3c4d5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('character_portraits', sa.Column('content_sha256', sa.String(64), nullable=True))


def downgrade():
    op.drop_column('character_portraits', 'content_sha256')
