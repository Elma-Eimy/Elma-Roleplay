"""保留角色包素材来源和事务内幂等导入回执。"""
from alembic import op
import sqlalchemy as sa

revision = "e0f1a2b3c4d5"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("character_portraits", sa.Column("source_type", sa.String(100), nullable=True))
    op.add_column("character_portraits", sa.Column("source_name", sa.Text(), nullable=True))
    op.add_column("character_portraits", sa.Column("source_uri", sa.Text(), nullable=True))
    op.create_table("character_package_imports",
                    sa.Column("token", sa.String(32), primary_key=True),
                    sa.Column("request_hash", sa.String(64), nullable=False),
                    sa.Column("character_id", sa.Integer(), sa.ForeignKey("characters.id", ondelete="SET NULL"), nullable=True),
                    sa.Column("result_json", sa.Text(), nullable=False))


def downgrade():
    op.drop_table("character_package_imports")
    op.drop_column("character_portraits", "source_uri")
    op.drop_column("character_portraits", "source_name")
    op.drop_column("character_portraits", "source_type")
