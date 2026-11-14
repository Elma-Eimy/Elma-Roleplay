"""可见单元、导演审计与正常终止原因；保留 v1 全文权限。"""
from alembic import op
from sqlalchemy import Column, Integer, String, Text, ForeignKeyConstraint, UniqueConstraint, CheckConstraint
import sqlalchemy as sa

revision = "b0d1e2f3a4b5"
down_revision = "a9c0d1e2f3a4"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("group_round_candidates", Column("protocol_version", Integer,
        CheckConstraint("protocol_version IN (1, 2)", name="ck_group_protocol_version"), nullable=False, server_default="1"))
    op.add_column("group_round_candidates", Column("finish_reason", String(30),
        CheckConstraint("finish_reason IN ('wait_user', 'step_limit', 'no_visible_basis')", name="ck_group_finish_reason")))
    op.create_index("uq_group_content_candidate", "group_content_items", ["id", "candidate_id", "session_id"], unique=True)
    op.create_table('group_content_units',
        Column('id', Integer, primary_key=True),
        Column('item_id', Integer, nullable=False),
        Column('candidate_id', Integer, nullable=False),
        Column('session_id', Integer, nullable=False),
        Column('unit_index', Integer, nullable=False),
        Column('kind', String(20), nullable=False),
        Column('source_start', Integer),
        Column('source_end', Integer),
        Column('text', Text),
        ForeignKeyConstraint(['item_id', 'candidate_id', 'session_id'], ['group_content_items.id', 'group_content_items.candidate_id', 'group_content_items.session_id'], ondelete='CASCADE'),
        UniqueConstraint('id', 'session_id', name='uq_group_unit_scope'),
        UniqueConstraint('item_id', 'unit_index', name='uq_group_unit_index'),
        CheckConstraint("unit_index >= 0 AND ((kind = 'user' AND source_start >= 0 AND source_end >= source_start AND source_start IS NOT NULL AND source_end IS NOT NULL AND text IS NULL) OR (kind IN ('speech', 'action', 'thought', 'legacy') AND source_start IS NULL AND source_end IS NULL AND text IS NOT NULL AND length(text) > 0))", name='ck_group_unit_shape'), sqlite_autoincrement=True)
    op.create_table('group_unit_visibility',
        Column('unit_id', Integer, primary_key=True),
        Column('recipient_persona_id', Integer, primary_key=True),
        Column('session_id', Integer, nullable=False),
        Column('decision', String(10), nullable=False),
        ForeignKeyConstraint(['unit_id', 'session_id'], ['group_content_units.id', 'group_content_units.session_id'], ondelete='CASCADE'),
        ForeignKeyConstraint(['session_id', 'recipient_persona_id'], ['session_personas.session_id', 'session_personas.id'], deferrable=True, initially='DEFERRED'),
        CheckConstraint("decision IN ('visible', 'hidden')", name='ck_group_unit_decision'), sqlite_autoincrement=False)
    op.create_table('group_director_steps',
        Column('id', Integer, primary_key=True),
        Column('candidate_id', Integer, nullable=False),
        Column('session_id', Integer, nullable=False),
        Column('stage', String(30), nullable=False),
        Column('step_index', Integer, nullable=False),
        Column('expected_revision', Integer, nullable=False),
        Column('result_revision', Integer, nullable=False),
        Column('speaker_persona_id', Integer),
        Column('item_id', Integer),
        Column('decision_json', Text, nullable=False),
        Column('reason_code', String(30)),
        Column('model', String(200), nullable=False),
        Column('policy_version', Integer, nullable=False),
        ForeignKeyConstraint(['candidate_id', 'session_id'], ['group_round_candidates.id', 'group_round_candidates.session_id'], ondelete='CASCADE'),
        ForeignKeyConstraint(['item_id', 'candidate_id', 'session_id'], ['group_content_items.id', 'group_content_items.candidate_id', 'group_content_items.session_id'], ondelete='CASCADE'),
        ForeignKeyConstraint(['session_id', 'speaker_persona_id'], ['session_personas.session_id', 'session_personas.id'], deferrable=True, initially='DEFERRED'),
        UniqueConstraint('candidate_id', 'step_index', name='uq_group_director_index'),
        CheckConstraint('step_index >= 1 AND expected_revision >= 0 AND result_revision = expected_revision + 1 AND policy_version IN (1, 2)', name='ck_group_director_revision'),
        CheckConstraint("(stage = 'user_visibility' AND item_id IS NOT NULL AND speaker_persona_id IS NULL) OR (stage = 'utterance_visibility' AND item_id IS NOT NULL AND speaker_persona_id IS NOT NULL) OR (stage = 'next_action' AND item_id IS NULL AND speaker_persona_id IS NOT NULL) OR (stage = 'finish' AND item_id IS NULL AND speaker_persona_id IS NULL)", name='ck_group_director_shape'), sqlite_autoincrement=True)
    op.create_index('ix_group_unit_recipient', 'group_unit_visibility', ['recipient_persona_id', 'decision', 'unit_id'])
    bind = op.get_bind()
    rows = bind.execute(sa.text("SELECT i.id, i.candidate_id, i.session_id, i.kind, i.content, r.user_content "
        "FROM group_content_items i JOIN group_round_candidates c ON c.id=i.candidate_id "
        "JOIN group_rounds r ON r.id=c.round_id")).all()
    for item_id, candidate_id, session_id, kind, content, user_content in rows:
        bind.execute(sa.text("INSERT INTO group_content_units(item_id,candidate_id,session_id,unit_index,kind,source_start,source_end,text) "
            "VALUES(:item,:candidate,:session,0,:kind,:start,:end,:text)"),
            dict(item=item_id, candidate=candidate_id, session=session_id, kind="user" if kind == "user" else "legacy",
                 start=0 if kind == "user" else None, end=len(user_content) if kind == "user" else None,
                 text=None if kind == "user" else content))
        unit_id = bind.execute(sa.text("SELECT id FROM group_content_units WHERE item_id=:id"), dict(id=item_id)).scalar_one()
        bind.execute(sa.text("INSERT INTO group_unit_visibility(unit_id,recipient_persona_id,session_id,decision) "
            "SELECT :unit,recipient_persona_id,session_id,decision FROM group_content_visibility WHERE item_id=:item"),
            dict(unit=unit_id,item=item_id))


def downgrade():
    bind = op.get_bind()
    if (bind.execute(sa.text("SELECT 1 FROM group_round_candidates WHERE protocol_version=2 OR finish_reason IS NOT NULL LIMIT 1")).first()
            or bind.execute(sa.text("SELECT 1 FROM group_director_steps LIMIT 1")).first()):
        raise RuntimeError("存在可见单元协议或导演终态，拒绝有损降级")
    for name in ("group_director_steps", "group_unit_visibility", "group_content_units"):
        op.drop_table(name)
    op.drop_index("uq_group_content_candidate", table_name="group_content_items")
    op.drop_column("group_round_candidates", "finish_reason")
    op.drop_column("group_round_candidates", "protocol_version")
