"""聊天回合 prepare/complete/abort 生命周期的离线回归测试。"""

import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.models import (
    Base,
    Character,
    ChatMessage,
    MessageRole,
    Session,
    SessionPersona,
)
from services.conversation import chat_turn_service


class ChatTurnServiceTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(engine)
        self.engine = engine
        self.db = sessionmaker(bind=engine)()

        character = Character(
            name="测试角色",
            description="测试设定",
            personality="平静",
            first_mes="你好",
        )
        session = Session(title="测试会话")
        self.db.add_all([character, session])
        self.db.flush()
        persona = SessionPersona(
            session_id=session.id,
            character_id=character.id,
            affection_score=0,
            current_mood="平静",
        )
        self.db.add(persona)
        self.db.commit()

        self.session_id = session.id
        self.persona_id = persona.id

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_prepare_and_abort_remove_new_user_message(self):
        turn = chat_turn_service.prepare_chat_turn(
            session_id=self.session_id,
            user_message="这条消息随后失败",
            is_regenerate=False,
            db=self.db,
        )
        message_id = turn.user_message.id
        self.assertIsNotNone(self.db.get(ChatMessage, message_id))

        removed = chat_turn_service.abort_chat_turn(turn, self.db)

        self.assertTrue(removed)
        self.assertIsNone(self.db.get(ChatMessage, message_id))

    def test_regenerate_abort_preserves_existing_turn(self):
        user_message = ChatMessage(
            session_id=self.session_id,
            role=MessageRole.user,
            content="原用户消息",
            is_active=True,
        )
        self.db.add(user_message)
        self.db.flush()
        assistant_message = ChatMessage(
            session_id=self.session_id,
            role=MessageRole.assistant,
            content="原回复",
            parent_id=user_message.id,
            is_active=True,
        )
        self.db.add(assistant_message)
        self.db.commit()

        turn = chat_turn_service.prepare_chat_turn(
            session_id=self.session_id,
            is_regenerate=True,
            db=self.db,
        )
        removed = chat_turn_service.abort_chat_turn(turn, self.db)

        self.assertFalse(removed)
        self.assertIsNotNone(self.db.get(ChatMessage, user_message.id))
        self.assertIsNotNone(self.db.get(ChatMessage, assistant_message.id))

    def test_complete_delegates_one_consistent_turn_payload(self):
        turn = chat_turn_service.prepare_chat_turn(
            session_id=self.session_id,
            user_message="用户消息",
            db=self.db,
        )
        candidates = [{"id": 8, "content": "回复"}]

        with patch.object(
            chat_turn_service.session_service,
            "save_chat_response",
            return_value=(8, 12, candidates),
        ) as save_mock:
            completed = chat_turn_service.complete_chat_turn(
                turn=turn,
                reply_text="回复",
                reasoning_content="",
                emotion_tag="开心",
                affection_change=2,
                db=self.db,
            )

        self.assertEqual(8, completed.assistant_message_id)
        self.assertEqual(12, completed.affection_score)
        self.assertEqual(candidates, completed.candidates)
        self.assertEqual(turn.user_message.id, save_mock.call_args.kwargs["user_msg_id"])
        self.assertFalse(save_mock.call_args.kwargs["is_regenerate"])

    def test_complete_persists_reply_and_persona_state_atomically(self):
        turn = chat_turn_service.prepare_chat_turn(
            session_id=self.session_id,
            user_message="用户消息",
            db=self.db,
        )

        completed = chat_turn_service.complete_chat_turn(
            turn=turn,
            reply_text="真实回复",
            reasoning_content="测试思考",
            emotion_tag="开心",
            affection_change=3,
            db=self.db,
        )

        reply = self.db.get(ChatMessage, completed.assistant_message_id)
        persona = self.db.get(SessionPersona, self.persona_id)
        self.assertEqual("真实回复", reply.content)
        self.assertEqual(turn.user_message.id, reply.parent_id)
        self.assertEqual(3, completed.affection_score)
        self.assertEqual(3, persona.affection_score)
        self.assertEqual("开心", persona.current_mood)
        self.assertEqual(1, len(completed.candidates))

    def test_prepare_reports_domain_error_without_http_dependency(self):
        with self.assertRaises(chat_turn_service.ChatTurnError) as raised:
            chat_turn_service.prepare_chat_turn(
                session_id=999999,
                user_message="不存在",
                db=self.db,
            )

        self.assertEqual(404, raised.exception.status_code)
        self.assertEqual("Session not found", raised.exception.detail)


if __name__ == "__main__":
    unittest.main()
