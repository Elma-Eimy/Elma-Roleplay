"""记忆测试共用数据与模型替身。"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from core.database import get_db
from core.models import Base, Character, Session, SessionPersona, ChatMessage, MessageRole, MemoryChunk, MemoryType
from routers.sessions import router
from services.memory import memory_consolidation_service as service
from services.memory.session_memory_query_service import query_session_memories, get_character_memory_overview
from services.conversation.session_service import create_session_service


class MemoryConsolidationFixture:
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.character = Character(name="林墨", description="测试角色", first_mes="你好")
        self.session = Session(title="当前故事")
        self.db.add_all([self.character, self.session])
        self.db.flush()
        self.persona = SessionPersona(session_id=self.session.id, character_id=self.character.id)
        self.db.add(self.persona)
        self.db.flush()
        self.first_message = ChatMessage(session_id=self.session.id, role=MessageRole.user, content="第一次", is_active=True)
        self.last_message = ChatMessage(session_id=self.session.id, role=MessageRole.user, content="第二次", is_active=True)
        self.db.add_all([self.first_message, self.last_message])
        self.db.commit()
        self.one = self.memory("用户和林墨在雨夜的车站相遇。", source=self.first_message.id)
        self.two = self.memory("那次车站相遇时，林墨把伞借给了用户。", source=self.last_message.id)
        self.app = FastAPI()
        self.app.include_router(router, prefix="/sessions")
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(self.app)

    def tearDown(self):
        self.client.close()
        self.db.close()
        self.engine.dispose()

    def memory(self, content, source=None, persona=None):
        persona = persona or self.persona
        row = MemoryChunk(persona_id=persona.id, origin_session_id=persona.session_id,
                          content=content, memory_type=MemoryType.event, importance_score=.7,
                          source_start_message_id=source, source_message_id=source)
        self.db.add(row)
        self.db.flush()
        row.chroma_doc_id = f"mem_{row.id}"
        self.db.commit()
        return row

    def payload(self):
        return {"groups": [{"kind": "event", "source_ids": [self.one.id, self.two.id],
                            "content": "用户和林墨在雨夜的车站相遇，林墨把伞借给了用户。", "reason": "同一次车站相遇的互补细节"}]}

    def preview(self, payload=None, session_id=None, after_id=0, mode="full"):
        provider = MagicMock()
        provider.generate.return_value = SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=json.dumps(payload or self.payload(), ensure_ascii=False)))])
        with patch.object(service, "get_llm_provider", return_value=provider):
            return service.preview(session_id or self.session.id, after_id, self.db, mode)

    def model_response(self, content, finish_reason="stop"):
        return SimpleNamespace(choices=[SimpleNamespace(
            message=SimpleNamespace(content=content), finish_reason=finish_reason)])

    def view(self, session_id=None, status="active"):
        return query_session_memories(session_id=session_id or self.session.id, q=None,
                                      scope="all", status=status, limit=100, offset=0, db=self.db)

    def fork(self, message_id=None, parent_id=None):
        result = create_session_service(self.character.id, parent_id or self.session.id,
                                        "分支", None, message_id or self.last_message.id, self.db)
        return result["session_id"]

    def assert_overview_matches_lists(self):
        overview = get_character_memory_overview(character_id=self.character.id, limit=50, offset=0, db=self.db)
        for story in overview["sessions"]:
            self.assertEqual(self.view(story["session_id"])["facets"], story["memory_stats"])

