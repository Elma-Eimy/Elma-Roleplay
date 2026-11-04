"""群聊 HTTP 契约及单聊/群聊双向访问边界。"""
import asyncio
from copy import deepcopy
import unittest
from unittest.mock import patch

from fastapi import Depends
from fastapi.testclient import TestClient
from pydantic import BaseModel
from application.factory import create_app
from application.session_routes import GroupSessionAPIRouter
from core.config import settings
from core.database import get_db
from core.locking import get_session_lock
from core.models import Session, ChatMessage, MessageRole
from tests.conversation import test_group_session_service as fixtures


class GroupSessionRoutesTests(unittest.TestCase):
    def setUp(self):
        fixtures.GroupSessionServiceTests.setUp(self)
        self.app = create_app()
        self.app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        self.payload = {"title": "  group  ", "user_nickname": "user", "shared_setting": "  ", "members": [
            {"character_id": 1, "origin": {"mode": "single_snapshot", "session_id": 10}},
            {"character_id": 2, "origin": {"mode": "card"}},
        ]}

    def test_create_list_detail_and_delete_roundtrip(self):
        response = self.client.post("/group-sessions", json=self.payload)
        self.assertEqual(200, response.status_code, response.text)
        group = response.json()
        group_id = group["session_id"]
        self.assertEqual("group", group["title"])
        self.assertIsNone(group["shared_setting"])
        self.assertFalse(group["can_generate"])
        self.assertEqual(2, group["members"][0]["origin"]["inherited_memory_count"])
        self.assertEqual(10, group["members"][0]["origin"]["source_session_id"])
        self.assertEqual(group, self.client.get(f"/group-sessions/{group_id}").json())
        page = self.client.get("/group-sessions?limit=1&offset=0").json()
        self.assertEqual([group], page["sessions"])
        self.assertEqual(1, page["total"])
        self.assertEqual(1, self.client.get("/sessions/recent").json()["total"])
        self.assertEqual(409, self.client.get(f"/sessions/{group_id}").status_code)
        deleted = self.client.post(f"/group-sessions/{group_id}/delete")
        self.assertEqual(200, deleted.status_code, deleted.text)
        self.assertEqual(2, deleted.json()["members_deleted"])
        self.assertEqual(404, self.client.get(f"/group-sessions/{group_id}").status_code)
        self.assertIsNotNone(self.db.get(Session, 10))

    def test_group_targets_reject_single_and_snapshot_sources_reject_group(self):
        self.assertEqual(409, self.client.get("/group-sessions/10").status_code)
        self.assertEqual(409, self.client.post("/group-sessions/10/delete").status_code)
        group_id = self.client.post("/group-sessions", json=self.payload).json()["session_id"]
        payload = deepcopy(self.payload)
        payload["members"][0]["origin"]["session_id"] = group_id
        result = self.client.post("/group-sessions", json=payload)
        self.assertEqual(409, result.status_code, result.text)
        self.assertEqual(1, self.client.get("/group-sessions").json()["total"])

    def test_request_constraints_fail_before_partial_creation(self):
        cases = []
        for change in (
            {"title": " "}, {"user_nickname": "x" * 51}, {"shared_setting": "x" * 20001},
            {"members": self.payload["members"][:1]}, {"members": self.payload["members"] * 2},
            {"members": [self.payload["members"][0]] * 2}, {"persona_id": 999},
        ):
            cases.append({**self.payload, **change})
        for origin in ({"mode": "card", "session_id": 10}, {"mode": "single_snapshot"},
                       {"mode": "other"}, {"mode": "single_snapshot", "session_id": True},
                       {"mode": "single_snapshot", "source_session_id": 10}):
            payload = deepcopy(self.payload)
            payload["members"][0]["origin"] = origin
            cases.append(payload)
        for payload in cases:
            with self.subTest(payload=str(payload)[:120]):
                result = self.client.post("/group-sessions", json=payload)
                self.assertEqual(422, result.status_code, result.text)
        self.assertEqual(0, self.client.get("/group-sessions").json()["total"])
        self.assertEqual(422, self.client.get("/group-sessions?limit=101").status_code)
        self.assertEqual(422, self.client.get("/group-sessions?offset=-1").status_code)

    def test_missing_resources_and_mismatched_source_character(self):
        for character_id, source_id, status in ((999, 10, 404), (1, 999, 404), (3, 10, 422)):
            payload = deepcopy(self.payload)
            payload["members"][0]["character_id"] = character_id
            payload["members"][0]["origin"]["session_id"] = source_id
            result = self.client.post("/group-sessions", json=payload)
            self.assertEqual(status, result.status_code, result.text)
        self.assertEqual(404, self.client.get("/group-sessions/999").status_code)
        self.assertEqual(404, self.client.post("/group-sessions/999/delete").status_code)

    def test_key_is_required_in_header_for_every_group_route(self):
        with patch.object(settings, "ACCESS_API_KEY", "fixture-key"):
            for method, path in (("GET", "/group-sessions"), ("POST", "/group-sessions"),
                                 ("GET", "/group-sessions/10"), ("POST", "/group-sessions/10/delete")):
                response = self.client.request(method, path, json=self.payload if path == "/group-sessions" and method == "POST" else None)
                self.assertEqual(403, response.status_code, response.text)
            self.assertEqual(200, self.client.get("/group-sessions", headers={"X-API-Key": "fixture-key"}).status_code)

    def test_busy_source_and_group_delete_return_conflict(self):
        source_lock = get_session_lock(10)
        asyncio.run(source_lock.acquire())
        try:
            result = self.client.post("/group-sessions", json=self.payload)
            self.assertEqual(409, result.status_code, result.text)
        finally:
            source_lock.release()
        group_id = self.client.post("/group-sessions", json=self.payload).json()["session_id"]
        lock = get_session_lock(group_id)
        asyncio.run(lock.acquire())
        try:
            self.assertEqual(409, self.client.post(f"/group-sessions/{group_id}/delete").status_code)
        finally:
            lock.release()

    def test_new_group_routes_enforce_policy_on_typed_nested_resources(self):
        group_id = self.client.post("/group-sessions", json=self.payload).json()["session_id"]
        self.db.add(ChatMessage(id=100, session_id=group_id, role=MessageRole.user, content="group"))
        self.db.commit()
        class Payload(BaseModel):
            message_id: int
        router = GroupSessionAPIRouter()
        called = []
        @router.post("/probe")
        def probe(request: Payload, db=Depends(get_db)):
            called.append(request.message_id)
            return {}
        self.app.include_router(router)
        self.assertEqual(409, self.client.post("/probe", json={"message_id": 1}).status_code)
        self.assertEqual([], called)
        self.assertEqual(200, self.client.post("/probe", json={"message_id": 100}).status_code)
