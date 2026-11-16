"""记忆测试共用数据与模型替身。"""
import json
from types import SimpleNamespace
from unittest.mock import MagicMock
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from core.models import Base, Character, ChatMessage, MemoryType, MessageRole, MemoryChunk, Session, SessionPersona


class MemoryCardExtractionFixture:
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        character = Character(
            name="Lin Mo",
            description="A fictional investigator.",
            personality="calm",
            scenario="office",
            first_mes="Hello.",
        )
        session = Session(title="memory card test")
        self.db.add_all([character, session])
        self.db.flush()
        self.persona = SessionPersona(
            session_id=session.id,
            character_id=character.id,
            affection_score=0,
        )
        self.db.add(self.persona)
        self.db.commit()
        self.session_id = session.id

        self.messages = []
        for role, content in (
            (MessageRole.user, "I plan to move next month."),
            (MessageRole.assistant, "Is it because of work?"),
            (MessageRole.user, "Yes, to Hangzhou Binjiang for my new job."),
            (MessageRole.user, "My cat is named Doubao."),
        ):
            message = ChatMessage(
                session_id=self.session_id,
                role=role,
                content=content,
                is_active=True,
            )
            self.db.add(message)
            self.messages.append(message)
        self.db.commit()

        # 进入下一轮后，上述消息才成为可提纯的已确认历史；本条边界消息
        # 自身仍留在短期上下文，不应进入本批提纯。
        self.confirming_message = ChatMessage(
            session_id=self.session_id,
            role=MessageRole.user,
            content="Please continue.",
            is_active=True,
        )
        self.db.add(self.confirming_message)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    @staticmethod
    def _provider_with_payload(payload):
        content = json.dumps(payload, ensure_ascii=False)
        return SimpleNamespace(
            generate=MagicMock(
                return_value=SimpleNamespace(
                    choices=[SimpleNamespace(
                        message=SimpleNamespace(content=content)
                    )]
                )
            )
        )

    def _write_candidate(self, content, **fields):
        row = MemoryChunk(persona_id=self.persona.id, origin_session_id=self.session_id,
                          content=content, memory_type=MemoryType.fact, importance_score=.4, **fields)
        self.db.add(row)
        self.db.flush()
        row.chroma_doc_id = f"mem_{row.id}"
        return row

    def _candidate_query(self, **kwargs):
        from services.memory.memory_write_candidates import retrieve_write_candidates
        return retrieve_write_candidates(
            self.persona.id, self.persona.character_id, "用户的猫叫豆包", self.db,
            memory_type=MemoryType.fact, temporal_status="unknown", temporal_note=None, **kwargs)

