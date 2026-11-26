"""记忆测试共用数据与模型替身。"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from core.models import Base, Character, Session, SessionPersona, ChatMessage, MessageRole, MemoryEventBuffer
from services.memory import memory_extraction_service as extraction
from services.conversation.session_service import create_session_service


class MemoryEventBufferFixture:
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)

        @event.listens_for(self.engine, "connect")
        def enable_fk(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.factory = sessionmaker(bind=self.engine)
        self.db = self.factory()
        character = Character(name="林墨", description="调查员", first_mes="你好。")
        story = Session(title="事件缓冲测试")
        self.db.add_all([character, story])
        self.db.flush()
        self.persona = SessionPersona(session_id=story.id, character_id=character.id)
        self.db.add(self.persona)
        self.db.commit()
        self.session_id = story.id
        self.current_user = None
        self.advance("用户与林墨开始约会。")

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def advance(self, text="用户与林墨继续谈心。"):
        if self.current_user is None:
            self.current_user = ChatMessage(session_id=self.session_id, role=MessageRole.user,
                                            content="一起去海边吧。", is_active=True)
            self.db.add(self.current_user)
            self.db.flush()
        first = self.current_user
        reply = ChatMessage(session_id=self.session_id, role=MessageRole.assistant, content=text, is_active=True)
        self.current_user = ChatMessage(session_id=self.session_id, role=MessageRole.user, content="请继续。", is_active=True)
        self.db.add_all([reply, self.current_user])
        self.db.commit()
        self.source_ids = [first.id, reply.id]

    def card(self, text="用户与林墨在海边开始约会，正在谈心。", **fields):
        return {"content": text, "memory_type": "event", "importance_score": .6,
                "temporal_status": "historical", "event_status": "ongoing", "buffer_id": None,
                "source_start_message_id": self.source_ids[0], "source_end_message_id": self.source_ids[-1], **fields}

    def extract(self, cards, entities=None, relations=None, *, force=False, callback=None):
        payload = {"memories": cards, "entities": entities or [], "relations": relations or []}
        response = SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload, ensure_ascii=False)))])
        provider = SimpleNamespace(generate=MagicMock(return_value=response))
        if callback:
            def respond(**_):
                callback()
                return response
            provider.generate.side_effect = respond
        with patch.object(extraction, "get_llm_provider", return_value=provider), \
             patch.object(extraction, "resolve_memory_relationship_via_llm", return_value={"relation": "coexist"}):
            count = extraction.summarize_and_store_memory(self.session_id, self.db, flush_events=force)
        return count, provider

    def buffer(self):
        return self.db.query(MemoryEventBuffer).one()

    def fork(self, message_id):
        result = create_session_service(character_id=self.persona.character_id, parent_session_id=self.session_id,
                                        title="分支", greeting_index=None, start_message_id=message_id, db=self.db)
        return result["persona_id"]
