"""Completion timestamps upgrade old jobs without inventing historical times."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
import core.database as database


class MemoryCompletionMigrationTests(unittest.TestCase):
    def test_upgrade_and_downgrade_preserve_jobs(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine("sqlite:///" + (Path(directory) / "jobs.db").as_posix())
            config = Config()
            config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
            try:
                with patch.object(database, "engine", engine):
                    command.upgrade(config, "a4b5c6d7e8f9")
                    with engine.begin() as db:
                        for sql in (
                            "INSERT INTO characters (id,name,description,first_mes) VALUES (1,'fixture','test','hello')",
                            "INSERT INTO sessions (id,title) VALUES (1,'story')",
                            "INSERT INTO session_personas (id,session_id,character_id) VALUES (1,1,1)",
                            "INSERT INTO memory_extraction_jobs (id,persona_id,kind,payload_json,status) VALUES (1,1,'candidates','{}','completed')",
                        ):
                            db.execute(text(sql))
                    command.upgrade(config, "head")
                    with engine.begin() as db:
                        self.assertIsNone(db.execute(text("SELECT completed_at FROM memory_extraction_jobs WHERE id=1")).scalar())
                        db.execute(text("UPDATE memory_extraction_jobs SET completed_at='2026-10-28 01:02:03' WHERE id=1"))
                    command.downgrade(config, "a4b5c6d7e8f9")
                    self.assertNotIn("completed_at", {c["name"] for c in inspect(engine).get_columns("memory_extraction_jobs")})
                    with engine.connect() as db:
                        self.assertEqual([(1, "{}", "completed")], list(db.execute(text("SELECT id,payload_json,status FROM memory_extraction_jobs"))))
                    command.upgrade(config, "head")
            finally:
                engine.dispose()
