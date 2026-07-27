from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import get_db
from core.models import (
    Base,
    Character,
    ChatMessage,
    MessageRole,
    Session,
    SessionPersona,
)
from routers.sessions import router
from services.conversation.session_service import get_recent_sessions


class RecentSessionsTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()

        character = Character(
            name="测试角色",
            description="用于测试最近会话接口",
            first_mes="你好",
            avatar_path="assets/avatar.png",
        )
        older_session = Session(
            title="较早会话",
            created_at=datetime(2026, 1, 1, 10, 0, 0),
            updated_at=datetime(2026, 1, 1, 11, 0, 0),
        )
        newer_session = Session(
            title="最近会话",
            created_at=datetime(2026, 1, 2, 10, 0, 0),
            updated_at=datetime(2026, 1, 2, 11, 0, 0),
        )
        self.db.add_all([character, older_session, newer_session])
        self.db.flush()
        self.db.add_all(
            [
                SessionPersona(
                    session_id=older_session.id,
                    character_id=character.id,
                    affection_score=3,
                    current_mood="平静",
                ),
                SessionPersona(
                    session_id=newer_session.id,
                    character_id=character.id,
                    affection_score=8,
                    current_mood="开心",
                ),
            ]
        )

        message_time = datetime(2026, 1, 2, 12, 0, 0)
        self.db.add_all(
            [
                ChatMessage(
                    session_id=newer_session.id,
                    role=MessageRole.assistant,
                    content="旧的有效消息",
                    is_active=True,
                    created_at=message_time,
                ),
                ChatMessage(
                    session_id=newer_session.id,
                    role=MessageRole.assistant,
                    content="已停用的更新消息",
                    is_active=False,
                    created_at=message_time + timedelta(minutes=2),
                ),
                ChatMessage(
                    session_id=newer_session.id,
                    role=MessageRole.user,
                    content="最新的有效消息",
                    is_active=True,
                    created_at=message_time + timedelta(minutes=1),
                ),
            ]
        )
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def test_service_returns_paginated_aggregate_with_two_queries(self):
        statements = []

        def record_statement(*args):
            statements.append(args[2])

        event.listen(self.engine, "before_cursor_execute", record_statement)
        try:
            result = get_recent_sessions(limit=1, offset=0, db=self.db)
        finally:
            event.remove(self.engine, "before_cursor_execute", record_statement)

        self.assertEqual(2, len(statements))
        self.assertEqual(2, result["total"])
        self.assertEqual(1, result["limit"])
        self.assertEqual(0, result["offset"])
        self.assertEqual("最近会话", result["sessions"][0]["title"])
        self.assertEqual("测试角色", result["sessions"][0]["character"]["name"])
        self.assertEqual("开心", result["sessions"][0]["persona"]["current_mood"])
        self.assertEqual(
            "最新的有效消息",
            result["sessions"][0]["last_message"]["content"],
        )

    def test_endpoint_is_not_shadowed_by_session_id_route(self):
        app = FastAPI()
        app.include_router(router, prefix="/sessions")
        app.dependency_overrides[get_db] = lambda: self.db

        with TestClient(app) as client:
            response = client.get("/sessions/recent", params={"limit": 1, "offset": 1})

        self.assertEqual(200, response.status_code)
        payload = response.json()
        self.assertEqual(2, payload["total"])
        self.assertEqual("较早会话", payload["sessions"][0]["title"])
        self.assertIsNone(payload["sessions"][0]["last_message"])

    def test_endpoint_rejects_invalid_pagination(self):
        app = FastAPI()
        app.include_router(router, prefix="/sessions")
        app.dependency_overrides[get_db] = lambda: self.db

        with TestClient(app) as client:
            response = client.get("/sessions/recent", params={"limit": 0, "offset": -1})

        self.assertEqual(422, response.status_code)


if __name__ == "__main__":
    unittest.main()
