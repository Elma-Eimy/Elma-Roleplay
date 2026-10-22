"""Old memory facts survive temporal provenance upgrades and downgrades."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text, inspect, event
import core.database as database


class MemoryFactMigrationTests(unittest.TestCase):
    def test_upgrade_downgrade_keeps_original_facts_and_version_links(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine("sqlite:///" + (Path(directory) / "facts.db").as_posix())
            @event.listens_for(engine, "connect")
            def foreign_keys(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
            config = Config()
            config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
            try:
                with patch.object(database, "engine", engine):
                    command.upgrade(config, "b7c8d9e0f1a2")
                    with engine.begin() as connection:
                        for statement in (
                            "INSERT INTO characters (id,name,description,first_mes) VALUES (1,'fixture','test','hello')",
                            "INSERT INTO sessions (id,title) VALUES (1,'old story')",
                            "INSERT INTO session_personas (id,session_id,character_id) VALUES (1,1,1)",
                            "INSERT INTO memory_chunks (id,persona_id,content,memory_type) VALUES (1,1,'old','fact')",
                            "INSERT INTO memory_chunks (id,persona_id,content,memory_type,supersedes_id) VALUES (2,1,'new','fact',1)",
                        ):
                            connection.execute(text(statement))
                    command.upgrade(config, "head")
                    with engine.begin() as connection:
                        self.assertEqual([("unknown", None, None)] * 2, list(connection.execute(text(
                            "SELECT temporal_status,temporal_note,source_evidence_json FROM memory_chunks"))))
                        connection.execute(text("UPDATE memory_chunks SET temporal_status='planned',temporal_note='next month' WHERE id=2"))
                    command.downgrade(config, "b7c8d9e0f1a2")
                    self.assertNotIn("temporal_status", [c["name"] for c in inspect(engine).get_columns("memory_chunks")])
                    with engine.connect() as connection:
                        self.assertEqual([(1, "old", None), (2, "new", 1)], list(connection.execute(text(
                            "SELECT id,content,supersedes_id FROM memory_chunks ORDER BY id"))))
                        self.assertEqual([], list(connection.execute(text("PRAGMA foreign_key_check"))))
                    command.upgrade(config, "head")
            finally:
                engine.dispose()
