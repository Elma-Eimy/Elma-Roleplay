"""群聊数据基础不开放单聊入口，拒绝时保留整个聚合。"""
import asyncio
import unittest
from datetime import datetime
from unittest.mock import patch

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from application.factory import create_app
from core.database import get_db
from core.locking import is_session_locked
from core.models import (Base, Character, ChatMessage, MessageRole, Session, SessionPersona,
                         MemoryExtractionJob, OutboxJob)
from services.conversation.session_access import SessionKindConflict
from services.conversation.session_service import get_character_sessions, get_recent_sessions
from services.memory.memory_extraction_jobs import request_capture, process_due_jobs, enqueue_candidates
from services.memory.memory_extraction_service import summarize_and_store_memory
from services.memory.cognition_service import update_cognition_state


class GroupSessionBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()
        self.addCleanup(self.db.close)
        self.db.add_all([
            Character(id=1, name="A", description="fixture", first_mes="hello"),
            Character(id=2, name="B", description="fixture", first_mes="hi"),
            Session(id=10, title="single", updated_at=datetime(2026, 1, 1)),
            Session(id=20, kind="group", title="group", updated_at=datetime(2026, 1, 2)),
        ])
        self.db.flush()
        self.db.add_all([
            SessionPersona(id=100, session_id=10, character_id=1),
            SessionPersona(id=200, session_id=20, character_id=1, member_slot=1),
            SessionPersona(id=300, session_id=20, character_id=2, member_slot=2),
            ChatMessage(id=1, session_id=20, role=MessageRole.user, content="group input"),
        ])
        self.db.flush()
        self.db.add(ChatMessage(id=2, session_id=20, role=MessageRole.assistant, content="group reply", parent_id=1))
        self.db.commit()
        self.app = create_app()
        self.app.dependency_overrides[get_db] = lambda: self.db
        # 不进入 lifespan，不运行迁移或后台 Worker。
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    def snapshot(self):
        return {table: self.db.execute(text('SELECT * FROM "' + table + '" ORDER BY 1')).all()
                for table in Base.metadata.tables}

    def test_every_existing_story_endpoint_rejects_group_before_side_effects(self):
        revision = "0" * 64
        cases = [
            ("GET", "/sessions/20", None),
            ("GET", "/sessions/20/history", None),
            ("GET", "/sessions/20/portrait", None),
            ("PUT", "/sessions/20/portrait", {"expected_revision": revision}),
            ("GET", "/sessions/20/role-state", None),
            ("PUT", "/sessions/20/role-state", {"expected_revision": revision, "patch": {}}),
            ("PUT", "/sessions/20/title", {"title": "changed"}),
            ("DELETE", "/sessions/20", None),
            ("POST", "/sessions/20/delete", None),
            ("GET", "/sessions/20/memory-processing", None),
            ("POST", "/sessions/20/trigger_summary", None),
            ("POST", "/sessions/20/trigger_cognition", None),
            ("GET", "/sessions/20/compile_prompt", None),
            ("GET", "/sessions/20/memories", None),
            ("POST", "/sessions/20/memories", {"content": "new memory"}),
            ("PUT", "/sessions/20/memories/999", {"content": "changed", "importance_score": 0.8}),
            ("DELETE", "/sessions/20/memories/999", None),
            ("GET", "/sessions/20/memory-consolidations", None),
            ("POST", "/sessions/20/memory-consolidations/preview", {}),
            ("POST", "/sessions/20/memory-consolidations/999/apply", {"group_ids": [0]}),
            ("PUT", "/sessions/20/memory-consolidations/999/groups/0", {"expected_revision": 0}),
            ("POST", "/sessions/20/memory-consolidations/999/undo", None),
            ("PUT", "/sessions/messages/2", {"content": "changed"}),
            ("DELETE", "/sessions/messages/2", None),
            ("POST", "/sessions/messages/2/delete", None),
            ("POST", "/sessions/create", {"character_id": 1, "parent_session_id": 20}),
            ("POST", "/chat", {"session_id": 20, "user_message": "hello"}),
            ("POST", "/chat/stream", {"session_id": 20, "user_message": "hello"}),
            ("POST", "/chat/switch_candidate", {"message_id": 2}),
            ("POST", "/utils/tts", {"message_id": 2, "text": "hello"}),
            ("DELETE", "/characters/1", None),
        ]
        original = self.snapshot()
        with patch("core.config.settings.TTS_ENABLED", True), patch(
            "services.infrastructure.llm_provider.get_llm_provider", side_effect=AssertionError("must not call model")
        ):
            for method, url, body in cases:
                with self.subTest(method=method, url=url):
                    response = self.client.request(method, url, json=body)
                    self.assertEqual(409, response.status_code, response.text)
                    self.assertFalse(is_session_locked(20))
                    self.assertEqual(original, self.snapshot())

    def test_lists_filter_groups_before_count_and_pagination(self):
        recent = get_recent_sessions(1, 0, self.db)
        self.assertEqual(1, recent["total"])
        self.assertEqual([10], [item["id"] for item in recent["sessions"]])
        for include_last_message in (False, True):
            page = get_character_sessions(character_id=1, include_last_message=include_last_message,
                                          limit=1, offset=0, db=self.db)
            self.assertEqual(1, page["total"])
            self.assertEqual([10], [item["id"] for item in page["sessions"]])
            self.assertFalse(page["has_more"])
        self.assertEqual([], get_recent_sessions(1, 1, self.db)["sessions"])

    def test_background_entrypoints_reject_group_without_enqueuing(self):
        actions = [
            lambda: request_capture(200, self.db),
            lambda: enqueue_candidates(200, [], [], [], [], {}, self.db),
            lambda: summarize_and_store_memory(20, self.db),
            lambda: update_cognition_state(200, self.db),
        ]
        with patch("services.memory.memory_extraction_service.get_llm_provider") as model:
            for action in actions:
                with self.assertRaises(SessionKindConflict):
                    action()
            model.assert_not_called()
        self.assertEqual(0, self.db.query(MemoryExtractionJob).count())
        self.assertEqual(0, self.db.query(OutboxJob).count())

    def test_worker_cancels_unsupported_persisted_job_before_planning(self):
        job = MemoryExtractionJob(persona_id=200, kind="capture", payload_json="{}")
        self.db.add(job)
        self.db.commit()
        with patch("services.memory.memory_extraction_jobs._plan") as plan, patch(
            "services.memory.memory_extraction_service.summarize_and_store_memory"
        ) as extract:
            self.assertEqual(0, process_due_jobs(self.db, force=True))
            plan.assert_not_called()
            extract.assert_not_called()
        self.db.refresh(job)
        self.assertEqual("cancelled", job.status)
        self.assertEqual("unsupported_session_kind", job.last_error_code)

    def test_prompt_assembly_rejects_group_before_retrieval(self):
        from services.conversation.context_assembler import assemble_prompt_context
        with patch("services.conversation.context_assembler.retrieve_joint_memories") as retrieve:
            with self.assertRaises(SessionKindConflict):
                asyncio.run(assemble_prompt_context(20, self.db.get(Character, 1),
                            self.db.get(SessionPersona, 200), self.db.get(ChatMessage, 1), None, self.db))
            retrieve.assert_not_called()

    def test_tts_type_check_precedes_disabled_setting_and_cache_creation(self):
        from services.tts_service import TTSService
        with patch("core.config.settings.TTS_ENABLED", False), patch("services.tts_service.os.makedirs") as mkdir:
            response = self.client.post("/utils/tts", json={"message_id": 2, "text": "hello"})
            self.assertEqual(409, response.status_code, response.text)
            with self.assertRaises(SessionKindConflict):
                TTSService.get_instance().generate_speech_sync("hello", message_id=2, db=self.db)
            mkdir.assert_not_called()
