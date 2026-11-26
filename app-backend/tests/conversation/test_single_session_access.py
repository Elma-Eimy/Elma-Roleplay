"""单聊入口拒绝跨类型资源，内部读取复用同一份会话。"""
import asyncio
import subprocess
import sys
import unittest
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import Base, Character, Session, SessionPersona, ChatMessage, MessageRole
from services.conversation import session_access, session_service, session_query_service, role_state_service, context_assembler
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

    def test_query_compatibility_exports_share_the_domain_implementation(self):
        for name in (
            "get_recent_sessions", "get_character_sessions", "get_session_history_page",
            "get_session_history_with_inheritance", "_history_for_session",
            "get_candidates_by_parent", "_candidates_for_session",
        ):
            with self.subTest(name=name):
                self.assertIs(getattr(session_query_service, name), getattr(session_service, name))

    def test_detail_query_preserves_missing_persona_and_resource_behavior(self):
        with self.single_checks() as checks:
            result = session_query_service.get_session_detail(1, self.db)
        checks.assert_called_once()
        self.assertEqual(1, result["id"])
        self.assertEqual(1, result["persona"]["id"])
        self.assertEqual("fixture", result["character"]["name"])
        self.assertIsNone(session_query_service.get_session_detail(999, self.db))
        with self.assertRaises(session_access.SessionKindConflict):
            session_query_service.get_session_detail(2, self.db)
        self.db.add(Session(id=3))
        self.db.commit()
        empty = session_query_service.get_session_detail(3, self.db)
        self.assertIsNone(empty["persona"])
        self.assertIsNone(empty["character"])

    def test_query_reads_preserve_the_callers_write_transaction(self):
        character = self.db.get(Character, 1)
        character.name = "caller pending name"
        self.db.flush()
        result = session_query_service.get_session_detail(1, self.db)
        messages, candidates = session_query_service.get_session_history_page(1, self.db, 20)
        self.assertEqual("caller pending name", result["character"]["name"])
        self.assertEqual([1], [message.id for message in messages])
        self.assertEqual({}, candidates)
        self.assertTrue(self.db.connection().connection.driver_connection.in_transaction)
        self.db.expire(character)
        self.assertEqual("caller pending name", character.name)
        self.db.rollback()
        self.assertEqual("fixture", character.name)

    def test_history_queries_exclude_ancestors_and_other_story_candidates(self):
        parent = Session(id=3)
        self.db.add(parent)
        self.db.flush()
        self.db.add(SessionPersona(id=3, session_id=3, character_id=1))
        self.db.add_all([
            ChatMessage(id=3, session_id=3, role=MessageRole.user, content="parent fork"),
            ChatMessage(id=4, session_id=3, role=MessageRole.assistant, parent_id=3, content="parent future"),
            ChatMessage(id=5, session_id=1, role=MessageRole.assistant, parent_id=1, content="child active"),
            ChatMessage(id=6, session_id=1, role=MessageRole.assistant, parent_id=1,
                        content="child alternative", is_active=False),
            ChatMessage(id=7, session_id=2, role=MessageRole.assistant, parent_id=2, content="other story"),
        ])
        self.db.flush()
        child = self.db.get(Session, 1)
        child.parent_session_id = parent.id
        child.fork_message_id = 3
        self.db.get(SessionPersona, 1).parent_persona_id = 3
        self.db.commit()

        messages = session_query_service.get_session_history_with_inheritance(1, self.db, 20)
        self.assertEqual(["hello", "child active"], [message.content for message in messages])
        page, candidates = session_query_service.get_session_history_page(1, self.db, 20, before_id=5)
        self.assertEqual([1], [message.id for message in page])
        self.assertEqual({}, candidates)
        grouped = session_query_service.get_candidates_by_parent(1, [1, 2, 3], self.db)
        self.assertEqual({1: [5, 6]}, {key: [row.id for row in rows] for key, rows in grouped.items()})

    def test_query_module_import_does_not_initialize_lifecycle_or_runtime(self):
        script = (
            "import sys; import services.conversation.session_query_service; "
            "forbidden = ('services.conversation.session_service', 'core.config', "
            "'core.database', 'services.memory'); "
            "loaded = [name for name in forbidden if name in sys.modules]; "
            "assert not loaded, loaded"
        )
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True,
            text=True, encoding="utf-8", timeout=30,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

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
