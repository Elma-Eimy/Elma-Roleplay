r"""Offline tests for conservative memory replacement and branch masking.

Run with:
    .\venv\Scripts\python.exe -m unittest tests.test_memory_versioning -v

No chat model, embedding API, or persistent vector store is called.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.models import (
    Base,
    Character,
    ChatMessage,
    MemoryChunk,
    MemoryType,
    MessageRole,
    Session,
    SessionPersona,
)
from services import cognition_service, memory_manager
from routers.sessions import get_session_memories


class MemoryVersioningTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.character = Character(
            name="Lin Mo",
            description="A fictional investigator.",
            personality="calm",
            scenario="office",
            first_mes="Hello.",
        )
        self.parent_session = Session(title="parent")
        self.db.add_all([self.character, self.parent_session])
        self.db.flush()
        self.child_session = Session(
            title="child", parent_session_id=self.parent_session.id
        )
        self.sibling_session = Session(
            title="sibling", parent_session_id=self.parent_session.id
        )
        self.db.add_all([self.child_session, self.sibling_session])
        self.db.flush()
        self.parent_persona = SessionPersona(
            session_id=self.parent_session.id,
            character_id=self.character.id,
        )
        self.db.add(self.parent_persona)
        self.db.flush()
        self.child_persona = SessionPersona(
            session_id=self.child_session.id,
            character_id=self.character.id,
            parent_persona_id=self.parent_persona.id,
        )
        self.sibling_persona = SessionPersona(
            session_id=self.sibling_session.id,
            character_id=self.character.id,
            parent_persona_id=self.parent_persona.id,
        )
        self.db.add_all([self.child_persona, self.sibling_persona])
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _memory(self, persona, content, *, supersedes=None):
        chunk = MemoryChunk(
            persona_id=persona.id,
            origin_session_id=persona.session_id,
            content=content,
            memory_type=MemoryType.fact,
            importance_score=0.8,
            supersedes_id=supersedes.id if supersedes else None,
        )
        self.db.add(chunk)
        self.db.flush()
        chunk.chroma_doc_id = f"mem_{chunk.id}"
        self.db.commit()
        return chunk

    @staticmethod
    def _collection_for(*chunks):
        collection = MagicMock()
        collection.count.return_value = len(chunks)
        collection.query.return_value = {
            "ids": [[chunk.chroma_doc_id for chunk in chunks]],
            "documents": [[chunk.content for chunk in chunks]],
            "metadatas": [[
                {
                    "persona_id": chunk.persona_id,
                    "memory_type": "fact",
                    "importance_score": chunk.importance_score,
                }
                for chunk in chunks
            ]],
            "distances": [[0.05 + index * 0.01 for index, _ in enumerate(chunks)]],
        }
        return collection

    def test_child_replacement_masks_parent_only_on_child_chain(self):
        old = self._memory(self.parent_persona, "用户住在北京。")
        new = self._memory(
            self.child_persona,
            "用户目前住在杭州。",
            supersedes=old,
        )

        child_chain = memory_manager.get_ancestor_persona_ids(
            self.child_persona.id, self.db
        )
        sibling_chain = memory_manager.get_ancestor_persona_ids(
            self.sibling_persona.id, self.db
        )
        self.assertEqual(
            {old.id},
            memory_manager.get_superseded_memory_ids(child_chain, self.db),
        )
        self.assertEqual(
            set(),
            memory_manager.get_superseded_memory_ids(sibling_chain, self.db),
        )

        collection = self._collection_for(old, new)
        with patch.object(
            memory_manager, "get_character_collection", return_value=collection
        ):
            recalled = memory_manager.retrieve_memories(
                persona_id=self.child_persona.id,
                character_id=self.character.id,
                query="用户住在哪里",
                db=self.db,
                top_k=3,
                min_importance=0.0,
            )

        self.assertEqual([new.id], [memory["id"] for memory in recalled])

    def test_retrieval_keeps_high_similarity_negation_pair_without_relation(self):
        likes = self._memory(
            self.parent_persona,
            "自从那件事情之后，她很喜欢用户。",
        )
        dislikes = self._memory(
            self.parent_persona,
            "自从那件事情之后，她很不喜欢用户。",
        )
        collection = self._collection_for(likes, dislikes)
        with patch.object(
            memory_manager, "get_character_collection", return_value=collection
        ):
            recalled = memory_manager.retrieve_memories(
                persona_id=self.parent_persona.id,
                character_id=self.character.id,
                query="那件事情之后她怎么看用户",
                db=self.db,
                top_k=3,
                min_importance=0.0,
            )

        self.assertEqual(2, len(recalled))

    def test_memory_api_exposes_branch_local_replacement_and_sources(self):
        old = self._memory(self.parent_persona, "用户住在北京。")
        old.source_start_message_id = None
        old.source_message_id = None
        new = self._memory(
            self.child_persona,
            "用户目前住在杭州。",
            supersedes=old,
        )

        response = get_session_memories(
            session_id=self.child_session.id,
            q=None,
            limit=20,
            offset=0,
            db=self.db,
        )
        by_id = {item["id"]: item for item in response}
        self.assertTrue(by_id[old.id]["is_superseded"])
        self.assertFalse(by_id[new.id]["is_superseded"])
        self.assertEqual(old.id, by_id[new.id]["supersedes_id"])
        self.assertIn("source_start_message_id", by_id[new.id])
        self.assertIn("source_message_id", by_id[new.id])

    def test_deleting_middle_version_reconnects_replacement_chain(self):
        first = self._memory(self.parent_persona, "用户住在北京。")
        middle = self._memory(
            self.child_persona,
            "用户目前住在杭州。",
            supersedes=first,
        )
        latest = self._memory(
            self.child_persona,
            "用户目前住在苏州。",
            supersedes=middle,
        )
        middle.chroma_doc_id = None
        self.db.commit()

        memory_manager.delete_memory_chunk(middle.id, self.db)
        self.db.refresh(latest)
        self.assertEqual(first.id, latest.supersedes_id)

    def test_relationship_resolver_parses_replace_and_falls_back_to_coexist(self):
        provider = SimpleNamespace(
            generate=MagicMock(
                return_value=SimpleNamespace(
                    choices=[SimpleNamespace(
                        message=SimpleNamespace(
                            content=json.dumps(
                                {
                                    "relation": "replace",
                                    "resolved_content": "用户目前住在杭州。",
                                },
                                ensure_ascii=False,
                            )
                        )
                    )]
                )
            )
        )
        with patch.object(
            cognition_service, "get_llm_provider", return_value=provider
        ):
            result = cognition_service.resolve_memory_relationship_via_llm(
                "用户住在北京。", "用户已经搬到杭州。"
            )
        self.assertEqual("replace", result["relation"])
        self.assertEqual("用户目前住在杭州。", result["resolved_content"])

        failing_provider = SimpleNamespace(
            generate=MagicMock(side_effect=ConnectionError("offline"))
        )
        with patch.object(
            cognition_service,
            "get_llm_provider",
            return_value=failing_provider,
        ):
            fallback = cognition_service.resolve_memory_relationship_via_llm(
                "旧信息", "新信息"
            )
        self.assertEqual(
            {"relation": "coexist", "resolved_content": "新信息"},
            fallback,
        )

    def test_memory_age_counts_only_user_turns_on_current_branch(self):
        source = ChatMessage(
            session_id=self.parent_session.id,
            role=MessageRole.assistant,
            content="来源事件",
            is_active=True,
        )
        parent_turn = ChatMessage(
            session_id=self.parent_session.id,
            role=MessageRole.user,
            content="父线分叉前的一轮",
            is_active=True,
        )
        parent_fork = ChatMessage(
            session_id=self.parent_session.id,
            role=MessageRole.assistant,
            content="父线分叉点",
            is_active=True,
        )
        self.db.add_all([source, parent_turn, parent_fork])
        self.db.flush()
        self.child_session.fork_message_id = parent_fork.id

        # These messages are outside the selected child timeline.
        self.db.add_all([
            ChatMessage(
                session_id=self.parent_session.id,
                role=MessageRole.user,
                content="父线分叉后的未来消息",
                is_active=True,
            ),
            ChatMessage(
                session_id=self.sibling_session.id,
                role=MessageRole.user,
                content="兄弟分支消息",
                is_active=True,
            ),
        ])

        copied_parent_boundary = ChatMessage(
            session_id=self.child_session.id,
            role=MessageRole.assistant,
            content=parent_fork.content,
            is_active=True,
        )
        child_turn = ChatMessage(
            session_id=self.child_session.id,
            role=MessageRole.user,
            content="子线有效一轮",
            is_active=True,
        )
        child_assistant = ChatMessage(
            session_id=self.child_session.id,
            role=MessageRole.assistant,
            content="角色长回复不单独算轮次",
            is_active=True,
        )
        child_fork = ChatMessage(
            session_id=self.child_session.id,
            role=MessageRole.assistant,
            content="子线分叉点",
            is_active=True,
        )
        self.db.add_all([
            copied_parent_boundary,
            child_turn,
            child_assistant,
            child_fork,
        ])
        self.db.flush()

        grandchild_session = Session(
            title="grandchild",
            parent_session_id=self.child_session.id,
            fork_message_id=child_fork.id,
        )
        self.db.add(grandchild_session)
        self.db.flush()
        grandchild_persona = SessionPersona(
            session_id=grandchild_session.id,
            character_id=self.character.id,
            parent_persona_id=self.child_persona.id,
        )
        self.db.add(grandchild_persona)
        self.db.flush()
        self.db.add_all([
            ChatMessage(
                session_id=self.child_session.id,
                role=MessageRole.user,
                content="子线分叉后的未来消息",
                is_active=True,
            ),
            ChatMessage(
                session_id=grandchild_session.id,
                role=MessageRole.assistant,
                content=child_fork.content,
                is_active=True,
            ),
            ChatMessage(
                session_id=grandchild_session.id,
                role=MessageRole.user,
                content="孙线有效一轮",
                is_active=True,
            ),
            ChatMessage(
                session_id=grandchild_session.id,
                role=MessageRole.user,
                content="孙线已撤销消息",
                is_active=False,
            ),
        ])
        self.db.commit()

        turns = memory_manager.calculate_memory_age_turns(
            memory_persona_id=self.parent_persona.id,
            source_message_id=source.id,
            current_persona_id=grandchild_persona.id,
            db=self.db,
        )
        self.assertEqual(3, turns)

        self.assertEqual(
            0,
            memory_manager.calculate_memory_age_turns(
                memory_persona_id=self.parent_persona.id,
                source_message_id=None,
                current_persona_id=grandchild_persona.id,
                db=self.db,
            ),
        )

    def test_user_fork_boundary_is_not_double_counted_after_its_own_memory(self):
        user_fork = ChatMessage(
            session_id=self.parent_session.id,
            role=MessageRole.user,
            content="以这条用户消息创建分支",
            is_active=True,
        )
        self.db.add(user_fork)
        self.db.flush()
        self.child_session.fork_message_id = user_fork.id

        copied_boundary = ChatMessage(
            session_id=self.child_session.id,
            role=MessageRole.user,
            content=user_fork.content,
            is_active=True,
        )
        actual_next_turn = ChatMessage(
            session_id=self.child_session.id,
            role=MessageRole.user,
            content="分支创建后的下一轮",
            is_active=True,
        )
        self.db.add_all([copied_boundary, actual_next_turn])
        self.db.commit()

        turns = memory_manager.calculate_memory_age_turns(
            memory_persona_id=self.parent_persona.id,
            source_message_id=user_fork.id,
            current_persona_id=self.child_persona.id,
            db=self.db,
        )
        self.assertEqual(1, turns)


if __name__ == "__main__":
    unittest.main(verbosity=2)
