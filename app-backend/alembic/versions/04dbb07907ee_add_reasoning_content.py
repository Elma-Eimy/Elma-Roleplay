"""add_reasoning_content

Revision ID: 04dbb07907ee
Revises: e8c3a2d02d0f
Create Date: 2026-06-28 16:55:51.351152

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: sa.Unicode = '04dbb07907ee'
down_revision: Union[str, None] = 'e8c3a2d02d0f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chat_messages', sa.Column('reasoning_content', sa.Text(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table('chat_messages') as batch_op:
        batch_op.drop_column('reasoning_content')
