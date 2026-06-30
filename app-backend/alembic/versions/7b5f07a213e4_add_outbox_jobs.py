"""add_outbox_jobs

Revision ID: 7b5f07a213e4
Revises: 04dbb07907ee
Create Date: 2026-06-29 20:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: sa.Unicode = '7b5f07a213e4'
down_revision: Union[str, None] = '04dbb07907ee'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'outbox_jobs',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('task_type', sa.String(length=50), nullable=False),
        sa.Column('payload', sa.Text(), nullable=False),
        sa.Column('status', sa.String(length=50), nullable=False, server_default='pending'),
        sa.Column('attempts', sa.Integer(), nullable=False, server_default='0'),
        sa.Column('max_attempts', sa.Integer(), nullable=False, server_default='5'),
        sa.Column('last_error', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True, server_default=sa.text('CURRENT_TIMESTAMP')),
        sa.Column('run_after', sa.DateTime(), nullable=False)
    )
    op.create_index('ix_outbox_jobs_id', 'outbox_jobs', ['id'], unique=False)
    op.create_index('ix_outbox_jobs_status', 'outbox_jobs', ['status'], unique=False)
    op.create_index('ix_outbox_jobs_run_after', 'outbox_jobs', ['run_after'], unique=False)


def downgrade() -> None:
    op.drop_index('ix_outbox_jobs_run_after', table_name='outbox_jobs')
    op.drop_index('ix_outbox_jobs_status', table_name='outbox_jobs')
    op.drop_index('ix_outbox_jobs_id', table_name='outbox_jobs')
    op.drop_table('outbox_jobs')
