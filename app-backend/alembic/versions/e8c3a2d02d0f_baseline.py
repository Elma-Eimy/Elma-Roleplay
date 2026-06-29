"""baseline

Revision ID: e8c3a2d02d0f
Revises: 
Create Date: 2026-06-28 16:55:16.628979

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: sa.Unicode = 'e8c3a2d02d0f'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. characters
    op.create_table(
        'characters',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('name', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('personality', sa.Text(), nullable=True),
        sa.Column('scenario', sa.Text(), nullable=True),
        sa.Column('first_mes', sa.Text(), nullable=False),
        sa.Column('mes_example', sa.Text(), nullable=True),
        sa.Column('creator_notes', sa.Text(), nullable=True),
        sa.Column('system_prompt_override', sa.Text(), nullable=True),
        sa.Column('post_history_instructions', sa.Text(), nullable=True),
        sa.Column('tags', sa.String(length=255), nullable=True),
        sa.Column('extensions', sa.Text(), nullable=True),
        sa.Column('avatar_path', sa.String(length=255), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_characters_id', 'characters', ['id'], unique=False)
    op.create_index('ix_characters_name', 'characters', ['name'], unique=False)

    # 2. sessions
    op.create_table(
        'sessions',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('parent_session_id', sa.Integer(), sa.ForeignKey('sessions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('title', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_sessions_id', 'sessions', ['id'], unique=False)
    op.create_index('ix_sessions_parent_session_id', 'sessions', ['parent_session_id'], unique=False)

    # 3. session_personas
    op.create_table(
        'session_personas',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False, unique=True),
        sa.Column('character_id', sa.Integer(), sa.ForeignKey('characters.id', ondelete='CASCADE'), nullable=False),
        sa.Column('parent_persona_id', sa.Integer(), sa.ForeignKey('session_personas.id', ondelete='SET NULL'), nullable=True),
        sa.Column('affection_score', sa.Integer(), nullable=True),
        sa.Column('cognition_state', sa.Text(), nullable=True),
        sa.Column('current_scenario_override', sa.Text(), nullable=True),
        sa.Column('current_mood', sa.String(length=50), nullable=True),
        sa.Column('last_summarized_msg_id', sa.Integer(), nullable=True),
        sa.Column('last_cognition_update_msg_id', sa.Integer(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_session_personas_id', 'session_personas', ['id'], unique=False)
    op.create_index('ix_session_personas_character_id', 'session_personas', ['character_id'], unique=False)
    op.create_index('ix_session_personas_parent_persona_id', 'session_personas', ['parent_persona_id'], unique=False)

    # 4. chat_messages (without reasoning_content!)
    op.create_table(
        'chat_messages',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('session_id', sa.Integer(), sa.ForeignKey('sessions.id', ondelete='CASCADE'), nullable=False),
        sa.Column('role', sa.String(length=50), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('emotion_tag', sa.String(length=50), nullable=True),
        sa.Column('affection_change', sa.Integer(), nullable=True),
        sa.Column('audio_path', sa.String(length=255), nullable=True),
        sa.Column('parent_id', sa.Integer(), sa.ForeignKey('chat_messages.id', ondelete='CASCADE'), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_chat_messages_id', 'chat_messages', ['id'], unique=False)
    op.create_index('ix_chat_messages_session_id', 'chat_messages', ['session_id'], unique=False)
    op.create_index('ix_chat_messages_parent_id', 'chat_messages', ['parent_id'], unique=False)

    # 5. Add foreign keys to session_personas for progress tracking
    with op.batch_alter_table('session_personas', schema=None) as batch_op:
        batch_op.create_foreign_key('fk_session_personas_last_summarized_msg_id', 'chat_messages', ['last_summarized_msg_id'], ['id'], ondelete='SET NULL')
        batch_op.create_foreign_key('fk_session_personas_last_cognition_update_msg_id', 'chat_messages', ['last_cognition_update_msg_id'], ['id'], ondelete='SET NULL')

    # 6. memory_chunks
    op.create_table(
        'memory_chunks',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('persona_id', sa.Integer(), sa.ForeignKey('session_personas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('origin_session_id', sa.Integer(), sa.ForeignKey('sessions.id', ondelete='SET NULL'), nullable=True),
        sa.Column('source_message_id', sa.Integer(), sa.ForeignKey('chat_messages.id', ondelete='SET NULL'), nullable=True),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('memory_type', sa.String(length=50), nullable=False),
        sa.Column('importance_score', sa.Float(), nullable=True),
        sa.Column('chroma_doc_id', sa.String(length=50), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_memory_chunks_id', 'memory_chunks', ['id'], unique=False)
    op.create_index('ix_memory_chunks_persona_id', 'memory_chunks', ['persona_id'], unique=False)
    op.create_index('ix_memory_chunks_origin_session_id', 'memory_chunks', ['origin_session_id'], unique=False)
    op.create_index('ix_memory_chunks_chroma_doc_id', 'memory_chunks', ['chroma_doc_id'], unique=True)

    # 7. graph_entities
    op.create_table(
        'graph_entities',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('persona_id', sa.Integer(), sa.ForeignKey('session_personas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('entity_type', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_graph_entities_id', 'graph_entities', ['id'], unique=False)
    op.create_index('ix_graph_entities_persona_id', 'graph_entities', ['persona_id'], unique=False)
    op.create_index('ix_graph_entities_name', 'graph_entities', ['name'], unique=False)

    # 8. graph_relations
    op.create_table(
        'graph_relations',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('persona_id', sa.Integer(), sa.ForeignKey('session_personas.id', ondelete='CASCADE'), nullable=False),
        sa.Column('source_id', sa.Integer(), sa.ForeignKey('graph_entities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('target_id', sa.Integer(), sa.ForeignKey('graph_entities.id', ondelete='CASCADE'), nullable=False),
        sa.Column('relation_type', sa.String(length=50), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('importance', sa.Float(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_graph_relations_id', 'graph_relations', ['id'], unique=False)
    op.create_index('ix_graph_relations_persona_id', 'graph_relations', ['persona_id'], unique=False)

    # 9. lorebooks
    op.create_table(
        'lorebooks',
        sa.Column('id', sa.Integer(), nullable=False, primary_key=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('scan_depth', sa.Integer(), nullable=True),
        sa.Column('token_budget', sa.Integer(), nullable=True),
        sa.Column('recursive_scanning', sa.Boolean(), nullable=True),
        sa.Column('entries', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
    )
    op.create_index('ix_lorebooks_id', 'lorebooks', ['id'], unique=False)

    # 10. character_lorebooks association table
    op.create_table(
        'character_lorebooks',
        sa.Column('character_id', sa.Integer(), sa.ForeignKey('characters.id', ondelete='CASCADE'), primary_key=True),
        sa.Column('lorebook_id', sa.Integer(), sa.ForeignKey('lorebooks.id', ondelete='CASCADE'), primary_key=True),
    )


def downgrade() -> None:
    op.drop_table('character_lorebooks')
    op.drop_table('lorebooks')
    op.drop_table('graph_relations')
    op.drop_table('graph_entities')
    op.drop_table('memory_chunks')
    
    with op.batch_alter_table('session_personas', schema=None) as batch_op:
        batch_op.drop_constraint('fk_session_personas_last_summarized_msg_id', type_='foreignkey')
        batch_op.drop_constraint('fk_session_personas_last_cognition_update_msg_id', type_='foreignkey')
        
    op.drop_table('chat_messages')
    op.drop_table('session_personas')
    op.drop_table('sessions')
    op.drop_table('characters')
