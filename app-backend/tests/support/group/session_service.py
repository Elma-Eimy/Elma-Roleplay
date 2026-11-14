"""群聊建库、来源故事与成员快照夹具。"""

import asyncio
import tempfile
from dataclasses import replace
from pathlib import Path
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from core.models import Base, Character, Session, SessionPersona, ChatMessage, MessageRole, MemoryChunk, MemoryType
from services.conversation.group import session_service as service
from services.conversation.group.session_service import GroupSessionDraft, GroupMember


class GroupSessionFixture:
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.engine = create_engine("sqlite:///" + (Path(self.directory.name) / "test.db").as_posix(),
                                    connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.sessions()
        self.addCleanup(self.db.close)
        self.db.add_all([Character(id=i, name=f"actor{i}", description="fixture", scenario="town", first_mes="hello") for i in (1, 2, 3)])
        self.db.add(Session(id=10, title="source"))
        self.db.flush()
        self.db.add(SessionPersona(id=100, session_id=10, character_id=1, affection_score=37,
                     current_mood="开心", cognition_state="knows user", current_scenario_override="library"))
        self.db.add_all([ChatMessage(id=1, session_id=10, role=MessageRole.user, content="first"),
                        ChatMessage(id=2, session_id=10, role=MessageRole.assistant, content="confirmed"),
                        ChatMessage(id=3, session_id=10, role=MessageRole.user, content="next"),
                        ChatMessage(id=4, session_id=10, role=MessageRole.assistant, content="latest",
                                    role_state_patch='{"scene":"current room"}')])
        self.db.flush()
        self.db.add_all([
            MemoryChunk(id=1, persona_id=100, content="confirmed fact", memory_type=MemoryType.fact,
                        origin_session_id=10, source_message_id=2, importance_score=0.9),
            MemoryChunk(id=2, persona_id=100, content="unconfirmed fact", memory_type=MemoryType.fact,
                        origin_session_id=10, source_message_id=4),
            MemoryChunk(id=3, persona_id=100, content="manual fact", memory_type=MemoryType.fact),
        ])
        self.db.commit()
        self.cards = GroupSessionDraft((GroupMember(1), GroupMember(2)))
        self.imported = replace(self.cards, members=(GroupMember(1, "single_snapshot", 10), GroupMember(2)))

    def create(self, draft=None):
        return asyncio.run(service.create_group_session(draft or self.imported, self.db))

    def snapshot(self):
        return {table: self.db.execute(text('SELECT * FROM "' + table + '" ORDER BY 1')).all()
                for table in Base.metadata.tables}
