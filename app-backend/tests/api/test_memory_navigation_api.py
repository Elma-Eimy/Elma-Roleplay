from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import get_db
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
from routers.characters import router as characters_router
from routers.sessions import router as sessions_router
from services.memory.session_memory_query_service import (
    get_character_memory_overview,
    query_session_memories,
)


class MemoryNavigationApiTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        self.character = Character(
            name="记忆测试角色",
            description="测试",
            first_mes="你好",
        )
        base_time = datetime(2026, 7, 28, 10, 0, 0)
        self.parent_session = Session(
            title="父故事",
            created_at=base_time,
            updated_at=base_time,
        )
        self.child_session = Session(
            title="子故事",
            created_at=base_time + timedelta(hours=1),
            updated_at=base_time + timedelta(hours=3),
        )
        self.sibling_session = Session(
            title="兄弟故事",
            created_at=base_time + timedelta(hours=2),
            updated_at=base_time + timedelta(hours=2),
        )
        self.db.add_all(
            [
                self.character,
                self.parent_session,
                self.child_session,
                self.sibling_session,
            ]
        )
        self.db.flush()
        self.child_session.parent_session_id = self.parent_session.id
        self.sibling_session.parent_session_id = self.parent_session.id
        self.db.flush()
        self.parent_session.updated_at = base_time
        self.child_session.updated_at = base_time + timedelta(hours=3)
        self.sibling_session.updated_at = base_time + timedelta(hours=2)
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
        self.db.flush()

        self.old_memory = self._memory(
            self.parent_persona,
            "用户曾经喜欢晴天。",
            created_at=base_time,
        )
        self.new_memory = self._memory(
            self.child_persona,
            "用户现在喜欢雨天。",
            supersedes=self.old_memory,
            created_at=base_time + timedelta(hours=4),
        )
        self.db.add_all(
            [
                ChatMessage(
                    session_id=self.child_session.id,
                    role=MessageRole.assistant,
                    content="最后的有效消息",
                    is_active=True,
                    created_at=base_time + timedelta(hours=5),
                ),
                ChatMessage(
                    session_id=self.child_session.id,
                    role=MessageRole.assistant,
                    content="不应展示的消息",
                    is_active=False,
                    created_at=base_time + timedelta(hours=6),
                ),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _memory(
        self,
        persona,
        content,
        *,
        supersedes=None,
        created_at=None,
    ):
        memory = MemoryChunk(
            persona_id=persona.id,
            origin_session_id=persona.session_id,
            content=content,
            memory_type=MemoryType.fact,
            importance_score=0.8,
            supersedes_id=supersedes.id if supersedes else None,
            created_at=created_at,
        )
        self.db.add(memory)
        self.db.flush()
        return memory

    def _query(self, session_id, **overrides):
        params = {
            "session_id": session_id,
            "q": None,
            "scope": "all",
            "status": "active",
            "limit": 20,
            "offset": 0,
            "db": self.db,
        }
        params.update(overrides)
        return query_session_memories(**params)

    def test_scope_and_status_are_applied_before_pagination(self):
        same_time = datetime(2026, 7, 29, 10, 0, 0)
        for index in range(20):
            self._memory(
                self.child_persona,
                f"本地记忆 {index}",
                created_at=same_time,
            )
        self.db.commit()

        inherited = self._query(
            self.child_session.id,
            scope="inherited",
            status="superseded",
            limit=20,
        )
        self.assertEqual(1, inherited["total"])
        self.assertEqual([self.old_memory.id], [item["id"] for item in inherited["items"]])

        local = self._query(
            self.child_session.id,
            scope="local",
            status="active",
            limit=100,
        )
        self.assertEqual(local["total"], local["facets"]["local_active"])
        equal_time_ids = [
            item["id"]
            for item in local["items"]
            if item["content"].startswith("本地记忆")
        ]
        self.assertEqual(sorted(equal_time_ids, reverse=True), equal_time_ids)

    def test_replacement_is_branch_local_and_facets_follow_search(self):
        child = self._query(self.child_session.id)
        sibling = self._query(self.sibling_session.id)
        self.assertEqual([self.new_memory.id], [item["id"] for item in child["items"]])
        self.assertEqual([self.old_memory.id], [item["id"] for item in sibling["items"]])

        searched = self._query(
            self.child_session.id,
            q="喜欢",
            status="all",
        )
        self.assertEqual(2, searched["total"])
        self.assertEqual(
            {
                "effective_total": 1,
                "local_active": 1,
                "inherited_active": 0,
                "superseded": 1,
            },
            searched["facets"],
        )

    def test_memory_endpoint_shape_and_validation(self):
        app = FastAPI()
        app.include_router(sessions_router, prefix="/sessions")
        app.dependency_overrides[get_db] = lambda: self.db
        with TestClient(app) as client:
            response = client.get(
                f"/sessions/{self.child_session.id}/memories",
                params={"scope": "all", "status": "all"},
            )
            invalid = client.get(
                f"/sessions/{self.child_session.id}/memories",
                params={"scope": "invalid", "limit": 101},
            )

        self.assertEqual(200, response.status_code)
        self.assertEqual(
            {"items", "total", "limit", "offset", "has_more", "facets"},
            set(response.json()),
        )
        self.assertEqual(422, invalid.status_code)

    def test_character_overview_is_branch_correct_and_bounded(self):
        statements = []

        def record_statement(*args):
            statements.append(args[2])

        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            overview = get_character_memory_overview(
                character_id=self.character.id,
                limit=50,
                offset=0,
                db=self.db,
            )
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)

        self.assertLessEqual(len(statements), 7)
        self.assertEqual(3, overview["story_count"])
        self.assertEqual(self.child_session.id, overview["recent_session_id"])
        by_id = {item["session_id"]: item for item in overview["sessions"]}
        self.assertEqual(
            {
                "effective_total": 1,
                "local_active": 1,
                "inherited_active": 0,
                "superseded": 1,
            },
            by_id[self.child_session.id]["memory_stats"],
        )
        self.assertEqual(
            {
                "effective_total": 1,
                "local_active": 0,
                "inherited_active": 1,
                "superseded": 0,
            },
            by_id[self.sibling_session.id]["memory_stats"],
        )
        self.assertEqual(
            "最后的有效消息",
            by_id[self.child_session.id]["last_message"]["content"],
        )

    def test_character_overview_endpoint_returns_404_and_422(self):
        app = FastAPI()
        app.include_router(characters_router, prefix="/characters")
        app.dependency_overrides[get_db] = lambda: self.db
        with TestClient(app) as client:
            missing = client.get("/characters/999999/memory-overview")
            invalid = client.get(
                f"/characters/{self.character.id}/memory-overview",
                params={"limit": 0},
            )

        self.assertEqual(404, missing.status_code)
        self.assertEqual(422, invalid.status_code)

    def test_navigation_indexes_are_present_in_model_metadata(self):
        memory_indexes = {
            row[1]
            for row in self.db.execute(text("PRAGMA index_list('memory_chunks')"))
        }
        message_indexes = {
            row[1]
            for row in self.db.execute(text("PRAGMA index_list('chat_messages')"))
        }
        self.assertIn("ix_memory_chunks_persona_created_id", memory_indexes)
        self.assertIn("ix_chat_messages_session_active_created_id", message_indexes)


if __name__ == "__main__":
    unittest.main()
