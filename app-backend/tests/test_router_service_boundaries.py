from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import (
    Base,
    Character,
    ChatMessage,
    MessageRole,
    OutboxJob,
    Session,
    SessionPersona,
)
from services import character_service
from services.conversation import message_service
from services.conversation.session_service import get_candidates_by_parent


ROOT = Path(__file__).resolve().parents[1]


class RouterServiceBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine("sqlite:///:memory:")
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()

        self.character = Character(
            name="Boundary Test",
            description="test",
            first_mes="hello",
        )
        self.session = Session(title="test")
        self.db.add_all([self.character, self.session])
        self.db.flush()
        self.persona = SessionPersona(
            session_id=self.session.id,
            character_id=self.character.id,
            affection_score=10,
        )
        self.db.add(self.persona)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    def _add_candidates(self):
        user = ChatMessage(
            session_id=self.session.id,
            role=MessageRole.user,
            content="question",
        )
        self.db.add(user)
        self.db.flush()
        first = ChatMessage(
            session_id=self.session.id,
            role=MessageRole.assistant,
            content="first",
            parent_id=user.id,
            is_active=True,
            affection_change=2,
            emotion_tag="calm",
        )
        second = ChatMessage(
            session_id=self.session.id,
            role=MessageRole.assistant,
            content="second",
            parent_id=user.id,
            is_active=False,
            affection_change=5,
            emotion_tag="happy",
        )
        self.db.add_all([first, second])
        self.db.commit()
        return user, first, second

    def test_core_package_import_has_no_database_side_effect(self):
        result = subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys, core; "
                "assert 'core.database' not in sys.modules; "
                "assert 'core.config' not in sys.modules",
            ],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(0, result.returncode, result.stdout + result.stderr)

    def test_switch_candidate_is_atomic_domain_operation(self):
        _, first, second = self._add_candidates()

        result = message_service.switch_candidate(second.id, self.db)

        self.db.refresh(first)
        self.db.refresh(second)
        self.db.refresh(self.persona)
        self.assertFalse(first.is_active)
        self.assertTrue(second.is_active)
        self.assertEqual(13, self.persona.affection_score)
        self.assertEqual("happy", self.persona.current_mood)
        self.assertEqual(second.id, result["message_id"])

    def test_history_candidates_are_loaded_as_one_grouped_batch(self):
        user, first, second = self._add_candidates()

        grouped = get_candidates_by_parent(
            self.session.id, [user.id], self.db
        )

        self.assertEqual([first.id, second.id], [m.id for m in grouped[user.id]])

    def test_message_edit_queues_old_audio_cleanup(self):
        message = ChatMessage(
            session_id=self.session.id,
            role=MessageRole.assistant,
            content="old",
            audio_path="cache/old.mp3",
        )
        self.db.add(message)
        self.db.commit()

        message_service.update_message(message.id, "new", self.db)

        job = self.db.query(OutboxJob).one()
        self.assertEqual("delete_audio", job.task_type)
        self.assertEqual(["cache/old.mp3"], json.loads(job.payload)["file_paths"])
        self.assertIsNone(message.audio_path)

    def test_character_service_owns_create_and_update_mapping(self):
        data = {
            "name": "Created Through Service",
            "description": "before",
            "first_mes": "hello",
            "tags": ["test"],
            "extensions": {"source": "unit"},
        }

        created = character_service.create_character(data, self.db)
        character_id = created["character_id"]
        data["name"] = "Updated Through Service"
        data["description"] = "after"
        updated = character_service.update_character(character_id, data, self.db)

        character = self.db.get(Character, character_id)
        self.assertEqual("Updated Through Service", updated["name"])
        self.assertEqual("after", character.description)
        self.assertEqual(["test"], json.loads(character.tags))

    def test_character_delete_commits_sql_and_cleanup_jobs_together(self):
        message = ChatMessage(
            session_id=self.session.id,
            role=MessageRole.assistant,
            content="reply",
            audio_path="cache/reply.mp3",
        )
        self.db.add(message)
        self.db.commit()
        character_id = self.character.id
        session_id = self.session.id

        result = character_service.delete_character_service(character_id, self.db)

        self.assertIsNone(self.db.get(Character, character_id))
        self.assertIsNone(self.db.get(Session, session_id))
        jobs = self.db.query(OutboxJob).order_by(OutboxJob.id).all()
        self.assertEqual(
            ["delete_vector_collection", "delete_audio"],
            [job.task_type for job in jobs],
        )
        self.assertEqual([session_id], result["session_ids"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
