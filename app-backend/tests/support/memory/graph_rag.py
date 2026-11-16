"""记忆测试共用数据与模型替身。"""
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from core.config import settings
from core.models import Base, Character, ChatMessage, MemoryChunk, MessageRole, Session, SessionPersona
from services.memory.graph_service import upsert_graph_data
from services.memory.graph_evidence import content_fingerprint, snapshot_sources


class GraphRagFixture:
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.old_min_importance = settings.APP_GRAPH_MIN_IMPORTANCE
        self.old_max_relations = settings.APP_GRAPH_MAX_RELATIONS
        settings.APP_GRAPH_MIN_IMPORTANCE = 0.0
        settings.APP_GRAPH_MAX_RELATIONS = 12

        self.character = Character(
            name="林墨",
            description="测试角色",
            personality="冷静",
            scenario="办公室",
            first_mes="你好",
        )
        self.parent_session = Session(title="parent")
        self.db.add_all([self.character, self.parent_session])
        self.db.flush()
        self.parent_persona = SessionPersona(
            session_id=self.parent_session.id,
            character_id=self.character.id,
        )
        self.db.add(self.parent_persona)
        self.db.flush()
        self.child_session = Session(
            title="child",
            parent_session_id=self.parent_session.id,
        )
        self.db.add(self.child_session)
        self.db.flush()
        self.child_persona = SessionPersona(
            session_id=self.child_session.id,
            character_id=self.character.id,
            parent_persona_id=self.parent_persona.id,
        )
        self.db.add(self.child_persona)
        self.db.commit()

    def tearDown(self):
        settings.APP_GRAPH_MIN_IMPORTANCE = self.old_min_importance
        settings.APP_GRAPH_MAX_RELATIONS = self.old_max_relations
        self.db.close()
        self.engine.dispose()

    def _upsert(self, persona, entities, relations):
        message = ChatMessage(session_id=persona.session_id, role=MessageRole.assistant,
                              content=json.dumps([entities, relations], ensure_ascii=False), is_active=True)
        self.db.add(message)
        self.db.flush()
        if persona.id == self.parent_persona.id and self.child_session.fork_message_id is None:
            self.child_session.fork_message_id = message.id
        self.db.add(ChatMessage(session_id=persona.session_id, role=MessageRole.user,
                                content="确认上一轮", is_active=True))
        memory = MemoryChunk(persona_id=persona.id, content=message.content, memory_type="fact",
                             importance_score=.8, origin_session_id=persona.session_id,
                             source_start_message_id=message.id, source_message_id=message.id)
        self.db.add(memory)
        self.db.flush()
        upsert_graph_data(persona.id, entities, relations, self.db,
                          source_messages=snapshot_sources([message]), memory_bindings={0: {
                              "memory_id": memory.id, "hash": content_fingerprint(memory.content),
                              "source_start": message.id, "source_end": message.id}})
        self.db.commit()
        return memory

