"""单聊入口拒绝跨类型资源，内部读取复用同一份会话。"""
import asyncio
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base, Character, Session, SessionPersona, ChatMessage, MessageRole
from services.conversation import session_access, session_service, role_state_service, context_assembler
from services.conversation.message_service import update_message
from services.media import character_portraits


class SingleSessionAccessTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://")
        self.addCleanup(self.engine.dispose)
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.db.close)
        self.db.add(Character(id=1, name="fixture", description="test", first_mes="hello"))
        self.db.add_all([Session(id=1), Session(id=2, kind="group")])
        self.db.flush()
        self.db.add_all([SessionPersona(id=1, session_id=1, character_id=1),
                         SessionPersona(id=2, session_id=2, character_id=1, member_slot=1)])
        self.db.add_all([ChatMessage(id=1, session_id=1, role=MessageRole.user, content="hello"),
                         ChatMessage(id=2, session_id=2, role=MessageRole.user, content="private")])
        self.db.commit()

    def single_checks(self):
        return patch.object(session_access, "_single", wraps=session_access._single)

    def test_loaders_resolve_ownership_and_preserve_missing_resource_behavior(self):
        for loader in (session_access.get_single_session, session_access.get_single_persona,
                       session_access.get_single_message):
            with self.subTest(loader=loader.__name__):
                self.assertIsNotNone(loader(1, self.db))
                self.assertIsNone(loader(999, self.db))
                with self.assertRaises(session_access.SessionKindConflict):
                    loader(2, self.db)

    def test_history_page_loads_once_for_history_and_candidates(self):
        with self.single_checks() as checks:
            messages, candidates = session_service.get_session_history_page(1, self.db, 20)
        self.assertEqual([1], [message.id for message in messages])
        self.assertEqual({}, candidates)
        checks.assert_called_once()
        self.assertIsNone(session_service.get_session_history_page(999, self.db, 20))

    def test_state_and_portrait_mutations_reuse_session_for_response(self):
        state = role_state_service.get_state(1, self.db)
        with self.single_checks() as checks:
            updated = role_state_service.update_state(1, {"scene": "library"}, state["revision"], self.db)
        self.assertEqual("library", updated["state"]["scene"])
        checks.assert_called_once()

        selection = character_portraits.get_selection(1, self.db)
        with self.single_checks() as checks:
            updated = character_portraits.update_selection(1, None, selection["revision"], self.db)
        self.assertIsNone(updated["portrait_id"])
        checks.assert_called_once()

    def test_message_mutation_reuses_resolved_owner(self):
        with self.single_checks() as checks:
            update_message(1, "edited", self.db)
        checks.assert_called_once()
        self.assertEqual("edited", self.db.get(ChatMessage, 1).content)
        with self.assertRaises(session_access.SessionKindConflict):
            update_message(2, "must not write", self.db)
        self.assertEqual("private", self.db.get(ChatMessage, 2).content)

    def test_prompt_reads_reuse_session_across_history_handoff_and_state(self):
        with self.single_checks() as checks, patch.object(context_assembler, "retrieve_joint_memories", return_value=[]), patch.object(
            context_assembler, "build_chat_messages", return_value=[]
        ):
            result = asyncio.run(context_assembler.assemble_prompt_context(
                1, self.db.get(Character, 1), self.db.get(SessionPersona, 1),
                self.db.get(ChatMessage, 1), None, self.db,
            ))
        self.assertEqual([], result)
        checks.assert_called_once()

    def test_reply_save_rejects_persona_from_another_story_before_writing(self):
        with self.assertRaisesRegex(ValueError, "does not belong"):
            session_service.save_chat_response(1, 2, 1, "reply", "", "calm", 1, False, None, self.db)
        self.assertEqual(2, self.db.query(ChatMessage).count())
