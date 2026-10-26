"""角色立绘资源与按剧情节点保存的手动选择。"""
from alembic import op
import sqlalchemy as sa

revision = "d9e0f1a2b3c4"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "character_portraits",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("character_id", sa.Integer(), sa.ForeignKey("characters.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("image_path", sa.String(255), nullable=False),
        # SQLite 不复用已删除资源的 ID，避免历史选择误指向新图。
        sqlite_autoincrement=True,
    )
    op.create_index("ix_character_portraits_id", "character_portraits", ["id"])
    op.create_index("ix_character_portraits_character_id", "character_portraits", ["character_id"])
    op.add_column("session_personas", sa.Column("portrait_base", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("chat_messages", sa.Column("portrait_selection", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("chat_messages", "portrait_selection")
    op.drop_column("session_personas", "portrait_base")
    op.drop_table("character_portraits")
