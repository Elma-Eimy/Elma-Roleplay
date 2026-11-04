"""Checkpoint upgrades preserve rows and event links; downgrade preserves memory text."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
import core.database as database


class EventCheckpointMigrationTests(unittest.TestCase):
    def test_upgrade_downgrade_and_foreign_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine("sqlite:///" + (Path(directory) / "checkpoints.db").as_posix())

            @event.listens_for(engine, "connect")
            def foreign_keys(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")

            config = Config()
            config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
            try:
                with patch.object(database, "engine", engine):
                    command.upgrade(config, "a3b4c5d6e7f8")
                    with engine.begin() as connection:
                        for statement in (
                            "INSERT INTO characters (id,name,description,first_mes) VALUES (1,'fixture','test','hello')",
                            "INSERT INTO sessions (id,title) VALUES (1,'story')",
                            "INSERT INTO session_personas (id,session_id,character_id) VALUES (1,1,1)",
                            "INSERT INTO memory_event_buffers (id,persona_id,payload_json) VALUES (1,1,'{}')",
                            "INSERT INTO memory_chunks (id,persona_id,content,memory_type) VALUES (1,1,'old fact','fact')",
                        ):
                            connection.execute(text(statement))
                    command.upgrade(config, "head")
                    with engine.begin() as connection:
                        self.assertEqual("open", connection.execute(text("SELECT status FROM memory_event_buffers WHERE id=1")).scalar())
                        self.assertIsNone(connection.execute(text("SELECT event_id FROM memory_chunks WHERE id=1")).scalar())
                        connection.execute(text("INSERT INTO memory_event_buffers (id,persona_id,payload_json,status) VALUES (2,1,'{}','checkpointed')"))
                        connection.execute(text("INSERT INTO memory_chunks (id,persona_id,content,memory_type,event_id) VALUES (2,1,'stage one','event',2)"))
                        connection.execute(text("INSERT INTO memory_chunks (id,persona_id,content,memory_type,event_id) VALUES (3,1,'stage two','event',2)"))
                    command.downgrade(config, "a3b4c5d6e7f8")
                    self.assertNotIn("event_id", {column["name"] for column in inspect(engine).get_columns("memory_chunks")})
                    with engine.connect() as connection:
                        self.assertEqual([("old fact",), ("stage one",), ("stage two",)], list(connection.execute(text("SELECT content FROM memory_chunks ORDER BY id"))))
                        self.assertEqual([1], list(connection.execute(text("SELECT id FROM memory_event_buffers")).scalars()))
                        self.assertEqual([], list(connection.execute(text("PRAGMA foreign_key_check"))))
                    command.upgrade(config, "head")
                    with engine.begin() as connection:
                        connection.execute(text("UPDATE memory_chunks SET event_id=1 WHERE id=2"))
                        connection.execute(text("DELETE FROM memory_event_buffers WHERE id=1"))
                        self.assertIsNone(connection.execute(text("SELECT event_id FROM memory_chunks WHERE id=2")).scalar())
                        connection.execute(text("DELETE FROM session_personas WHERE id=1"))
                        self.assertEqual(0, connection.execute(text("SELECT count(*) FROM memory_chunks")).scalar())
                        self.assertEqual([], list(connection.execute(text("PRAGMA foreign_key_check"))))
            finally:
                engine.dispose()
