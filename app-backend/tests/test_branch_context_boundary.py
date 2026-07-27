r"""分支上下文边界的离线回归测试。

运行方式：
    .\venv\Scripts\python.exe .\tests\test_branch_context_boundary.py

测试使用独立的内存 SQLite，不访问 ChromaDB、Embedding API 或对话模型。
"""

from __future__ import annotations

import asyncio
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.models import Base, Character, ChatMessage, MessageRole, Session
from services.conversation.context_assembler import get_parent_history_examples
from services.conversation.prompt_compiler import build_chat_messages
from services.conversation.session_service import create_session_service, safe_delete_session


if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


class BranchContextBoundaryTests(unittest.TestCase):
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
        self.SessionLocal = sessionmaker(
            autocommit=False,
            autoflush=False,
            bind=self.engine,
        )
        self.db = self.SessionLocal()
        self.character = Character(
            name="分支边界测试角色",
            description="用于验证分支不会读取未来消息。",
            first_mes="父会话开场白",
        )
        self.db.add(self.character)
        self.db.commit()
        self.db.refresh(self.character)

    def tearDown(self):
        self.db.close()
        # StaticPool 的内存数据库会随 engine 销毁；无需在 SQLite 的循环外键
        # （sessions ↔ chat_messages）上执行不可排序的 DROP TABLE。
        self.engine.dispose()

    def _create_root(self, title="父会话"):
        result = create_session_service(
            character_id=self.character.id,
            parent_session_id=None,
            title=title,
            greeting_index=None,
            start_message_id=None,
            db=self.db,
        )
        return self.db.get(Session, result["session_id"])

    def _append(self, session_id, role, content):
        message = ChatMessage(
            session_id=session_id,
            role=role,
            content=content,
            emotion_tag="平静" if role == MessageRole.assistant else None,
            affection_change=0,
            is_active=True,
        )
        self.db.add(message)
        self.db.commit()
        self.db.refresh(message)
        return message

    def _create_branch(self, parent, start_message_id, title="子会话"):
        result = create_session_service(
            character_id=self.character.id,
            parent_session_id=parent.id,
            title=title,
            greeting_index=None,
            start_message_id=start_message_id,
            db=self.db,
        )
        return self.db.get(Session, result["session_id"]), result

    def _compile_child_prompt(self, child, current_user_message):
        child_messages = self.db.query(ChatMessage).filter(
            ChatMessage.session_id == child.id,
            ChatMessage.is_active == True,
            ChatMessage.id < current_user_message.id,
        ).order_by(ChatMessage.id).all()
        recent_history = [
            {
                "role": message.role.value,
                "content": message.content,
                "emotion_tag": message.emotion_tag,
                "affection_change": message.affection_change,
            }
            for message in child_messages
        ]
        parent_history = get_parent_history_examples(child.persona, self.db)
        return build_chat_messages(
            character=child.persona.character,
            persona=child.persona,
            recent_history=recent_history,
            parent_history=parent_history,
            user_message=current_user_message.content,
            retrieved_memories=None,
            graph_knowledge=None,
        )

    def test_branch_prompt_stops_before_fork_and_does_not_duplicate_boundary(self):
        parent = self._create_root()
        before_fork = self._append(parent.id, MessageRole.user, "分叉点之前的消息 A")
        fork_message = self._append(parent.id, MessageRole.assistant, "被选中的分叉消息 B")

        child, result = self._create_branch(parent, fork_message.id)
        self.assertEqual(fork_message.id, child.fork_message_id)
        self.assertEqual(fork_message.id, result["fork_message_id"])

        # 子会话创建之后，父会话继续发展。这些消息绝不能进入子分支 Prompt。
        self._append(parent.id, MessageRole.user, "父会话未来消息 C")
        self._append(parent.id, MessageRole.assistant, "父会话未来消息 D")
        current = self._append(child.id, MessageRole.user, "子会话当前消息")

        messages = self._compile_child_prompt(child, current)
        compiled = "\n".join(message["content"] for message in messages)

        self.assertIn(before_fork.content, compiled)
        self.assertIn(fork_message.content, compiled)
        self.assertNotIn("父会话未来消息 C", compiled)
        self.assertNotIn("父会话未来消息 D", compiled)
        self.assertEqual(1, compiled.count(fork_message.content))

    def test_explicit_invalid_fork_message_is_rejected_without_creating_session(self):
        parent = self._create_root()
        session_count_before = self.db.query(Session).count()

        with self.assertRaisesRegex(ValueError, "does not belong to parent session"):
            self._create_branch(parent, start_message_id=999999)

        self.assertEqual(session_count_before, self.db.query(Session).count())

    def test_legacy_null_boundary_never_falls_back_to_latest_parent_messages(self):
        parent = self._create_root()
        parent_before = self._append(parent.id, MessageRole.user, "旧会话不应猜测的父历史")
        fork_message = self._append(parent.id, MessageRole.assistant, "旧分支复制的边界消息")
        child, _ = self._create_branch(parent, fork_message.id)

        # 模拟迁移前已经存在、无法可靠回填 fork_message_id 的子会话。
        child.fork_message_id = None
        self.db.commit()
        self._append(parent.id, MessageRole.user, "旧会话父时间线未来内容")
        current = self._append(child.id, MessageRole.user, "旧子会话当前消息")

        messages = self._compile_child_prompt(child, current)
        compiled = "\n".join(message["content"] for message in messages)

        self.assertNotIn(parent_before.content, compiled)
        self.assertNotIn("旧会话父时间线未来内容", compiled)
        # 已复制到子会话中的边界快照仍正常保留。
        self.assertEqual(1, compiled.count(fork_message.content))

    def test_deleting_middle_session_relinks_child_to_grandparent_boundary(self):
        grandparent = self._create_root(title="祖父会话")
        gp_fork = self._append(grandparent.id, MessageRole.assistant, "祖父分叉消息")
        parent, _ = self._create_branch(grandparent, gp_fork.id, title="中间会话")
        parent_fork = self._append(parent.id, MessageRole.assistant, "中间会话分叉消息")
        child, _ = self._create_branch(parent, parent_fork.id, title="孙会话")

        self.assertEqual(parent_fork.id, child.fork_message_id)
        safe_delete_session(parent.id, self.db)

        self.db.refresh(child)
        self.assertEqual(grandparent.id, child.parent_session_id)
        self.assertEqual(gp_fork.id, child.fork_message_id)
        self.assertEqual(grandparent.persona.id, child.persona.parent_persona_id)


if __name__ == "__main__":
    unittest.main(verbosity=2)
