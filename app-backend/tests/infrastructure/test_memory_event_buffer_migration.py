"""事件缓冲迁移保留旧记忆，支持回退及重新升级。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text, event
import core.database as database


class MemoryEventBufferMigrationTests(unittest.TestCase):
    def test_upgrade_downgrade_preserves_existing_memories_and_foreign_keys(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine("sqlite:///" + (Path(directory) / "events.db").as_posix())

            @event.listens_for(engine, "connect")
            def enable_fk(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")

            config = Config()
            config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
            try:
                with patch.object(database, "engine", engine):
                    command.upgrade(config, "f1a2b3c4d5e6")
                    with engine.begin() as connection:
                        for statement in (
                            "INSERT INTO characters (id,name,description,first_mes) VALUES (1,'fixture','test','hello')",
                            "INSERT INTO sessions (id,title) VALUES (1,'old story')",
                            "INSERT INTO session_personas (id,session_id,character_id) VALUES (1,1,1)",
                            "INSERT INTO memory_chunks (id,persona_id,content,memory_type) VALUES (1,1,'old memory','fact')",
                        ):
                            connection.execute(text(statement))
                    command.upgrade(config, "head")
                    self.assertIn("memory_event_buffers", inspect(engine).get_table_names())
                    with engine.begin() as connection:
                        connection.execute(text("INSERT INTO memory_event_buffers (persona_id,payload_json) VALUES (1,'{}')"))
                        self.assertEqual([(1, 1)], list(connection.execute(text(
                            "SELECT age_batches,revision FROM memory_event_buffers"))))
                    command.downgrade(config, "f1a2b3c4d5e6")
                    self.assertNotIn("memory_event_buffers", inspect(engine).get_table_names())
                    with engine.connect() as connection:
                        self.assertEqual([("old memory",)], list(connection.execute(text("SELECT content FROM memory_chunks"))))
                        self.assertEqual([], list(connection.execute(text("PRAGMA foreign_key_check"))))
                    command.upgrade(config, "head")
                    with engine.begin() as connection:
                        connection.execute(text("INSERT INTO memory_event_buffers (persona_id,payload_json) VALUES (1,'{}')"))
                        connection.execute(text("DELETE FROM session_personas WHERE id=1"))
                        self.assertEqual(0, connection.execute(text("SELECT count(*) FROM memory_event_buffers")).scalar())
            finally:
                engine.dispose()
