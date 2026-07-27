r"""Offline regression tests for context-aware retrieval queries.

Run with:
    .\venv\Scripts\python.exe .\tests\test_contextual_retrieval_query.py

No chat or embedding model is called.
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.models import Base, ChatMessage, MessageRole, Session
from services.conversation import context_assembler
from services.conversation.retrieval_query_service import build_contextual_retrieval_query


if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


class ContextualRetrievalQueryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        session = Session(title="retrieval query test")
        self.db.add(session)
        self.db.commit()
        self.session_id = session.id

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _append(self, role, content, *, active=True, session_id=None):
        message = ChatMessage(
            session_id=session_id or self.session_id,
            role=role,
            content=content,
            is_active=active,
        )
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message

    def test_current_question_is_enriched_with_three_recent_turns(self):
        old_user = self._append(MessageRole.user, "old topic that should expire")
        self._append(MessageRole.assistant, "old answer that should expire")
        recent_contents = []
        for index in range(1, 4):
            user_text = f"recent user turn {index} about Lin Mo"
            assistant_text = f"recent assistant turn {index} about the bureau"
            recent_contents.extend((user_text, assistant_text))
            self._append(MessageRole.user, user_text)
            self._append(MessageRole.assistant, assistant_text)
        current = self._append(MessageRole.user, "Where did he go later?")

        with (
            patch.object(settings, "APP_RETRIEVAL_CONTEXT_TURNS", 3),
            patch.object(settings, "APP_RETRIEVAL_QUERY_MAX_CHARS", 1200),
        ):
            query = build_contextual_retrieval_query(
                self.session_id, current, self.db
            )

        self.assertTrue(query.startswith("\u5f53\u524d\u95ee\u9898\uff1aWhere did he go later?"))
        for content in recent_contents:
            self.assertIn(content, query)
        self.assertNotIn(old_user.content, query)
        self.assertNotIn("old answer that should expire", query)

    def test_inactive_other_session_and_future_messages_are_excluded(self):
        self._append(MessageRole.user, "visible local subject")
        self._append(MessageRole.assistant, "inactive secret", active=False)

        other = Session(title="other timeline")
        self.db.add(other)
        self.db.commit()
        self._append(
            MessageRole.assistant,
            "parent future secret",
            session_id=other.id,
        )

        current = self._append(MessageRole.user, "What about that?")
        self._append(MessageRole.assistant, "local future secret")

        with (
            patch.object(settings, "APP_RETRIEVAL_CONTEXT_TURNS", 3),
            patch.object(settings, "APP_RETRIEVAL_QUERY_MAX_CHARS", 1200),
        ):
            query = build_contextual_retrieval_query(
                self.session_id, current, self.db
            )

        self.assertIn("visible local subject", query)
        self.assertNotIn("inactive secret", query)
        self.assertNotIn("parent future secret", query)
        self.assertNotIn("local future secret", query)

    def test_query_budget_preserves_current_question_at_both_ends(self):
        self._append(MessageRole.user, "history " * 200)
        self._append(MessageRole.assistant, "answer " * 200)
        current = self._append(
            MessageRole.user,
            "CURRENT_HEAD " + ("middle " * 100) + "CURRENT_TAIL",
        )

        with (
            patch.object(settings, "APP_RETRIEVAL_CONTEXT_TURNS", 3),
            patch.object(settings, "APP_RETRIEVAL_QUERY_MAX_CHARS", 200),
        ):
            query = build_contextual_retrieval_query(
                self.session_id, current, self.db
            )

        self.assertLessEqual(len(query), 200)
        self.assertIn("CURRENT_HEAD", query)
        self.assertIn("CURRENT_TAIL", query)

    def test_long_roleplay_replies_do_not_starve_selected_turns(self):
        markers = []
        for index in range(1, 4):
            user_marker = f"USER_TURN_{index}"
            assistant_marker = f"ASSISTANT_TURN_{index}"
            markers.extend((user_marker, assistant_marker))
            self._append(
                MessageRole.user,
                user_marker + " " + ("user context " * 80),
            )
            self._append(
                MessageRole.assistant,
                assistant_marker + " " + ("action and dialogue " * 120),
            )
        current = self._append(MessageRole.user, "What happened after that?")

        with (
            patch.object(settings, "APP_RETRIEVAL_CONTEXT_TURNS", 3),
            patch.object(settings, "APP_RETRIEVAL_QUERY_MAX_CHARS", 2400),
        ):
            query = build_contextual_retrieval_query(
                self.session_id, current, self.db
            )

        self.assertLessEqual(len(query), 2400)
        for marker in markers:
            self.assertIn(marker, query)

    def test_context_assembler_shares_one_query_with_memory_and_graph(self):
        db = MagicMock()
        character = SimpleNamespace(id=2)
        persona = SimpleNamespace(id=3)
        user_msg = SimpleNamespace(id=10, content="What about him?")

        with (
            patch.object(
                context_assembler,
                "build_contextual_retrieval_query",
                return_value="one contextual query",
            ) as builder_mock,
            patch.object(
                context_assembler.memory_manager,
                "retrieve_memories",
                return_value=[],
            ) as memory_mock,
            patch.object(
                context_assembler,
                "retrieve_graph_context",
                return_value="",
            ) as graph_mock,
            patch.object(
                context_assembler,
                "get_memory_handoff_history_limit",
                return_value=15,
            ),
            patch.object(
                context_assembler.session_service,
                "get_session_history_with_inheritance",
                return_value=[],
            ),
            patch.object(
                context_assembler,
                "get_parent_history_examples",
                return_value=[],
            ),
            patch.object(
                context_assembler,
                "build_chat_messages",
                return_value=[],
            ),
        ):
            asyncio.run(
                context_assembler.assemble_prompt_context(
                    session_id=1,
                    character=character,
                    persona=persona,
                    user_msg=user_msg,
                    old_reply=None,
                    db=db,
                )
            )

        builder_mock.assert_called_once_with(1, user_msg, db)
        self.assertEqual("one contextual query", memory_mock.call_args.kwargs["query"])
        graph_mock.assert_called_once_with(
            persona_id=3,
            query_text="one contextual query",
            db=db,
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
