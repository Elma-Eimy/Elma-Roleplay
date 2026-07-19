r"""短期历史到长期记忆无缝交接的离线回归测试。

运行方式：
    .\venv\Scripts\python.exe .\tests\test_memory_handoff.py

测试使用内存 SQLite 和函数替身，不调用对话或向量模型。
"""

from __future__ import annotations

import asyncio
import importlib
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.config import settings
from core.models import (
    Base,
    Character,
    ChatMessage,
    MessageRole,
    Session,
    SessionPersona,
)
from services import cognition_service
from services import context_assembler

chat_router = importlib.import_module("routers.chat")


if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


class MemoryHandoffTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )

        @event.listens_for(self.engine, "connect")
        def _enable_foreign_keys(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.close()

        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )()

        character = Character(
            name="记忆交接测试角色",
            description="测试角色",
            first_mes="你好",
        )
        session = Session(title="记忆交接测试会话")
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

    def tearDown(self):
        self.db.close()
        Base.metadata.drop_all(self.engine)
        self.engine.dispose()

    def _append_messages(self, count):
        messages = []
        for index in range(count):
            message = ChatMessage(
                session_id=self.session_id,
                role=MessageRole.user if index % 2 == 0 else MessageRole.assistant,
                content=f"交接测试消息 {index + 1}",
                is_active=True,
            )
            self.db.add(message)
            messages.append(message)
        self.db.commit()
        return messages

    def test_effective_trigger_is_clamped_before_short_history_eviction(self):
        with (
            patch.object(settings, "APP_CONTEXT_HISTORY_LIMIT", 15),
            patch.object(settings, "APP_MEMORY_EXTRACT_LIMIT", 20),
            patch.object(settings, "APP_MEMORY_HANDOFF_MARGIN", 2),
        ):
            self.assertEqual(
                13,
                cognition_service.get_effective_memory_extract_limit(),
            )

        # 用户显式配置了更早的阈值时应尊重该阈值。
        with (
            patch.object(settings, "APP_CONTEXT_HISTORY_LIMIT", 15),
            patch.object(settings, "APP_MEMORY_EXTRACT_LIMIT", 10),
            patch.object(settings, "APP_MEMORY_HANDOFF_MARGIN", 2),
        ):
            self.assertEqual(
                10,
                cognition_service.get_effective_memory_extract_limit(),
            )

    def test_unsummarized_messages_temporarily_expand_history_then_restore(self):
        messages = self._append_messages(18)
        with (
            patch.object(settings, "APP_CONTEXT_HISTORY_LIMIT", 15),
            patch.object(settings, "APP_MEMORY_EXTRACT_LIMIT", 20),
        ):
            self.assertEqual(
                18,
                cognition_service.get_memory_handoff_history_limit(
                    self.session_id,
                    self.db,
                ),
            )

            # 模拟提纯成功推进到第 10 条；只剩 8 条未总结消息后恢复常规窗口。
            self.persona.last_summarized_msg_id = messages[9].id
            self.db.commit()
            self.assertEqual(
                15,
                cognition_service.get_memory_handoff_history_limit(
                    self.session_id,
                    self.db,
                ),
            )

    def test_handoff_window_is_bounded_when_extraction_keeps_failing(self):
        self._append_messages(35)
        with (
            patch.object(settings, "APP_CONTEXT_HISTORY_LIMIT", 15),
            patch.object(settings, "APP_MEMORY_EXTRACT_LIMIT", 20),
        ):
            self.assertEqual(
                30,
                cognition_service.get_memory_handoff_history_limit(
                    self.session_id,
                    self.db,
                ),
            )

    def test_context_assembler_uses_handoff_limit_and_regenerate_compensation(self):
        db = MagicMock()
        character = SimpleNamespace(id=2)
        persona = SimpleNamespace(id=3)
        user_msg = SimpleNamespace(id=10, content="她之前说了什么？")

        with (
            patch.object(
                context_assembler.memory_manager,
                "get_memory_handoff_history_limit",
                return_value=18,
            ),
            patch.object(
                context_assembler.memory_manager,
                "retrieve_memories",
                return_value=[],
            ),
            patch.object(
                context_assembler,
                "retrieve_graph_context",
                return_value="",
            ),
            patch.object(
                context_assembler.session_service,
                "get_session_history_with_inheritance",
                return_value=[],
            ) as history_mock,
            patch.object(
                context_assembler,
                "_build_chat_messages",
                new=AsyncMock(return_value=[]),
            ),
        ):
            asyncio.run(context_assembler.assemble_prompt_context(
                session_id=1,
                character=character,
                persona=persona,
                user_msg=user_msg,
                old_reply=None,
                db=db,
            ))
            history_mock.assert_called_once_with(1, db, 18)

            history_mock.reset_mock()
            asyncio.run(context_assembler.assemble_prompt_context(
                session_id=1,
                character=character,
                persona=persona,
                user_msg=user_msg,
                old_reply=SimpleNamespace(id=11),
                db=db,
            ))
            history_mock.assert_called_once_with(1, db, 19)

    def test_auto_trigger_uses_effective_handoff_threshold(self):
        db = MagicMock()
        with (
            patch.object(chat_router, "SessionLocal", return_value=db),
            patch.object(
                chat_router.memory_manager,
                "get_unsummarized_count",
                side_effect=[12, 13],
            ),
            patch.object(
                chat_router.memory_manager,
                "get_effective_memory_extract_limit",
                return_value=13,
            ),
            patch.object(
                chat_router.memory_manager,
                "summarize_and_store_memory",
                return_value=1,
            ) as summarize_mock,
            patch.object(
                chat_router.memory_manager,
                "get_cognition_unseen_count",
                return_value=0,
            ),
        ):
            chat_router.run_auto_trigger_checks(session_id=1, persona_id=2)
            summarize_mock.assert_not_called()

            chat_router.run_auto_trigger_checks(session_id=1, persona_id=2)
            summarize_mock.assert_called_once_with(1, db)


if __name__ == "__main__":
    unittest.main(verbosity=2)
