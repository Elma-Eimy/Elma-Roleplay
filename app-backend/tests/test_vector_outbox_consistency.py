r"""Offline regression tests for SQLite-to-Chroma vector Outbox consistency."""

from __future__ import annotations

import asyncio
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.models import (
    Base,
    Character,
    MemoryChunk,
    MemoryType,
    OutboxJob,
    OutboxJobStatus,
    Session,
    SessionPersona,
)
from services import memory_manager, outbox_worker


class _StatefulCollection:
    def __init__(self):
        self.documents = {}
        self.upsert_calls = 0

    def upsert(self, *, ids, documents, metadatas):
        self.upsert_calls += 1
        for doc_id, document, metadata in zip(ids, documents, metadatas):
            self.documents[doc_id] = (document, metadata)

    def delete(self, *, ids):
        for doc_id in ids:
            self.documents.pop(doc_id, None)


class VectorOutboxConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        db_path = Path(self.temp_dir.name) / "outbox.sqlite3"
        self.engine = create_engine(
            f"sqlite:///{db_path.as_posix()}",
            connect_args={"check_same_thread": False},
        )
        Base.metadata.create_all(self.engine)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self.db = self.SessionLocal()

        character = Character(
            name="Outbox Test Character",
            description="test",
            personality="test",
            scenario="test",
            first_mes="test",
        )
        session = Session(title="outbox")
        self.db.add_all([character, session])
        self.db.flush()
        persona = SessionPersona(
            session_id=session.id,
            character_id=character.id,
        )
        self.db.add(persona)
        self.db.commit()
        self.character_id = character.id
        self.persona_id = persona.id
        self.session_id = session.id
        self.collection = _StatefulCollection()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()
        self.temp_dir.cleanup()

    def _run_worker(self):
        with (
            patch.object(outbox_worker, "SessionLocal", self.SessionLocal),
            patch.object(
                memory_manager,
                "get_character_collection",
                return_value=self.collection,
            ),
        ):
            asyncio.run(outbox_worker.process_pending_jobs())

    def _add_memory(self, content="用户住在北京。"):
        return memory_manager.add_memory_chunk(
            persona_id=self.persona_id,
            character_id=self.character_id,
            content=content,
            memory_type=MemoryType.fact,
            importance_score=0.8,
            origin_session_id=self.session_id,
            source_message_id=None,
            db=self.db,
        )

    def test_add_commits_memory_and_outbox_before_vector_write(self):
        chunk = self._add_memory()

        self.assertEqual({}, self.collection.documents)
        job = self.db.query(OutboxJob).one()
        self.assertEqual("upsert_vector", job.task_type)
        self.assertEqual(chunk.id, json.loads(job.payload)["memory_id"])

        self._run_worker()
        self.db.expire_all()
        self.assertEqual(0, self.db.query(OutboxJob).count())
        self.assertEqual("用户住在北京。", self.collection.documents[chunk.chroma_doc_id][0])

    def test_multiple_tasks_idempotently_write_latest_sqlite_value(self):
        chunk = self._add_memory("旧内容")
        memory_manager.update_memory_chunk(chunk.id, "最新内容", 0.9, self.db)

        self.assertEqual(2, self.db.query(OutboxJob).count())
        self._run_worker()

        self.assertEqual(1, len(self.collection.documents))
        self.assertEqual("最新内容", self.collection.documents[chunk.chroma_doc_id][0])

    def test_vector_failure_is_persisted_and_retry_can_succeed(self):
        self._add_memory()
        with (
            patch.object(outbox_worker, "SessionLocal", self.SessionLocal),
            patch.object(
                memory_manager,
                "get_character_collection",
                side_effect=ConnectionError("vector service offline"),
            ),
        ):
            asyncio.run(outbox_worker.process_pending_jobs())

        self.db.expire_all()
        job = self.db.query(OutboxJob).one()
        self.assertEqual(OutboxJobStatus.failed, job.status)
        self.assertEqual(1, job.attempts)
        self.assertIn("vector service offline", job.last_error)

        job.run_after = datetime.now() - timedelta(seconds=1)
        self.db.commit()
        self._run_worker()
        self.db.expire_all()
        self.assertEqual(0, self.db.query(OutboxJob).count())

    def test_expired_processing_lease_is_recovered(self):
        chunk = self._add_memory()
        job = self.db.query(OutboxJob).one()
        job.status = OutboxJobStatus.processing
        job.run_after = datetime.now() - timedelta(seconds=1)
        self.db.commit()

        self._run_worker()

        self.db.expire_all()
        self.assertEqual(0, self.db.query(OutboxJob).count())
        self.assertEqual("用户住在北京。", self.collection.documents[chunk.chroma_doc_id][0])

    def test_stale_upsert_task_cannot_resurrect_deleted_memory(self):
        chunk = self._add_memory()
        stale_payload = self.db.query(OutboxJob).one().payload
        memory_manager.delete_memory_chunk(chunk.id, self.db)

        with (
            patch.object(outbox_worker, "SessionLocal", self.SessionLocal),
            patch.object(
                memory_manager,
                "get_character_collection",
                return_value=self.collection,
            ),
        ):
            outbox_worker.handle_upsert_vector(stale_payload)

        self.assertEqual({}, self.collection.documents)


if __name__ == "__main__":
    unittest.main(verbosity=2)
