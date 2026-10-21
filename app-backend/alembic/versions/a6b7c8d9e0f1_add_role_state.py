"""Persist branch-local role state and per-candidate incremental updates."""

from alembic import op
import sqlalchemy as sa

revision = "a6b7c8d9e0f1"
down_revision = "f5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("session_personas", sa.Column("role_state_base", sa.Text(), nullable=True))
    op.add_column("chat_messages", sa.Column("role_state_patch", sa.Text(), nullable=True))
    op.add_column("chat_messages", sa.Column("role_state_manual", sa.Text(), nullable=True))


def downgrade():
    # 沿用现有迁移的原生 DROP COLUMN；重建父表会触发 SQLite 外键级联。
    op.drop_column("chat_messages", "role_state_manual")
    op.drop_column("chat_messages", "role_state_patch")
    op.drop_column("session_personas", "role_state_base")
