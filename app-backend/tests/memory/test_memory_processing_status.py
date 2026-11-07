"""Read-only, story-local memory progress and successful completion timestamps."""
from datetime import datetime
from unittest.mock import patch
import unittest

from fastapi.testclient import TestClient
from application.factory import create_app
from core.database import get_db
from core.models import MemoryExtractionJob, Session, SessionPersona
from services.memory import memory_extraction_jobs as jobs
from tests.memory import test_memory_event_buffer as fixture


class MemoryProcessingStatusTests(unittest.TestCase):
    setUp = fixture.MemoryEventBufferTests.setUp
    tearDown = fixture.MemoryEventBufferTests.tearDown
    advance = fixture.MemoryEventBufferTests.advance

    def client(self):
        app = create_app()
        def database():
            yield self.db
        app.dependency_overrides[get_db] = database
        return TestClient(app)

    def test_get_is_read_only_and_distinguishes_no_completion(self):
        with patch.object(jobs, "request_capture") as capture:
            response = self.client().get(f"/sessions/{self.session_id}/memory-processing")
        self.assertEqual(200, response.status_code)
        self.assertEqual({"session_id": self.session_id, "status": "completed", "pending_count": 0,
                          "processing_count": 0, "error_codes": [], "last_completed_at": None}, response.json())
        capture.assert_not_called()
        self.assertEqual(0, self.db.query(MemoryExtractionJob).count())

    def test_status_is_local_and_retry_priority_does_not_hide_running_work(self):
        other_session = Session(title="other branch")
        self.db.add(other_session)
        self.db.flush()
        other = SessionPersona(session_id=other_session.id, character_id=self.persona.character_id)
        self.db.add(other)
        self.db.flush()
        completed = datetime(2026, 10, 28, 1, 2, 3)
        self.db.add_all([
            MemoryExtractionJob(persona_id=self.persona.id, payload_json="{}", status="completed", completed_at=completed),
            MemoryExtractionJob(persona_id=self.persona.id, payload_json="{}", status="processing"),
            MemoryExtractionJob(persona_id=self.persona.id, payload_json="{}", status="retrying", last_error_code="extraction_failed"),
            MemoryExtractionJob(persona_id=other.id, payload_json="{}", status="retrying", last_error_code="other_branch"),
            MemoryExtractionJob(persona_id=other.id, payload_json="{}", status="completed", completed_at=datetime(2026, 10, 29)),
        ])
        self.db.commit()
        result = self.client().get(f"/sessions/{self.session_id}/memory-processing").json()
        self.assertEqual("retrying", result["status"])
        self.assertEqual(2, result["pending_count"])
        self.assertEqual(1, result["processing_count"])
        self.assertEqual(["extraction_failed"], result["error_codes"])
        self.assertEqual("2026-10-28T01:02:03Z", result["last_completed_at"])

    def test_missing_session_or_persona_and_cancelled_sources(self):
        client = self.client()
        self.assertEqual(404, client.get("/sessions/999999/memory-processing").status_code)
        empty = Session(title="no persona")
        self.db.add(empty)
        self.db.commit()
        self.assertEqual(409, client.get(f"/sessions/{empty.id}/memory-processing").status_code)
        self.db.add(MemoryExtractionJob(persona_id=self.persona.id, payload_json="{}", status="cancelled",
                                        last_error_code="sources_changed"))
        self.db.commit()
        result = client.get(f"/sessions/{self.session_id}/memory-processing").json()
        self.assertEqual("failed", result["status"])
        self.assertEqual(["sources_changed"], result["error_codes"])
        self.assertIsNone(result["last_completed_at"])

    def test_capture_completion_records_time_in_the_commit(self):
        jobs.request_capture(self.persona.id, self.db)
        with patch("services.memory.memory_extraction_service.summarize_and_store_memory"), \
             patch("services.memory.memory_extraction_service.get_unsummarized_count", return_value=0):
            jobs.process_due_jobs(self.db, self.persona.id)
        row = self.db.query(MemoryExtractionJob).one()
        self.assertEqual("completed", row.status)
        self.assertIsNotNone(row.completed_at)
        self.assertTrue(jobs.processing_status(self.persona.id, self.db)["last_completed_at"].endswith("Z"))
