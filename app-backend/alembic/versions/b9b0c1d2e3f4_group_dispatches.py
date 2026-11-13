"""为新共同群聊保存独立业务调度，旧候选继续读取原审计。"""
from alembic import op
import sqlalchemy as sa

revision = 'b9b0c1d2e3f4'
down_revision = 'b8a9b0c1d2e3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('group_round_candidates', sa.Column('dispatch_version', sa.Integer(),
        sa.CheckConstraint('dispatch_version IN (0, 1)', name='ck_group_dispatch_version'),
        nullable=False, server_default='0'))
    op.create_table('group_dispatches',
        sa.Column('id', sa.Integer(), primary_key=True),
        sa.Column('candidate_id', sa.Integer(), nullable=False),
        sa.Column('session_id', sa.Integer(), nullable=False),
        sa.Column('sequence', sa.Integer(), nullable=False),
        sa.Column('speaker_persona_id', sa.Integer(), nullable=False),
        sa.Column('response_reference', sa.String(80)),
        sa.Column('reason_code', sa.String(30), nullable=False),
        sa.Column('expected_revision', sa.Integer(), nullable=False),
        sa.Column('result_revision', sa.Integer(), nullable=False),
        sa.Column('completed_revision', sa.Integer()),
        sa.ForeignKeyConstraint(['candidate_id', 'session_id'],
            ['group_round_candidates.id', 'group_round_candidates.session_id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['session_id', 'speaker_persona_id'],
            ['session_personas.session_id', 'session_personas.id'], deferrable=True, initially='DEFERRED'),
        sa.UniqueConstraint('candidate_id', 'sequence', name='uq_group_dispatch_sequence'),
        sa.CheckConstraint('sequence >= 1 AND expected_revision >= 0 AND result_revision = expected_revision + 1 '
            'AND (completed_revision IS NULL OR completed_revision > result_revision)', name='ck_group_dispatch_revision'),
        sa.CheckConstraint("reason_code IN ('direct_response', 'follow_up')", name='ck_group_dispatch_reason'),
        sa.CheckConstraint('response_reference IS NULL OR length(response_reference) BETWEEN 1 AND 80',
            name='ck_group_dispatch_reference'), sqlite_autoincrement=True)


def downgrade():
    db = op.get_bind()
    if (db.exec_driver_sql('SELECT 1 FROM group_dispatches LIMIT 1').first()
            or db.exec_driver_sql('SELECT 1 FROM group_round_candidates WHERE dispatch_version != 0 LIMIT 1').first()):
        raise RuntimeError('仍有独立群聊调度，拒绝有损降级')
    op.drop_table('group_dispatches')
    op.drop_column('group_round_candidates', 'dispatch_version')
