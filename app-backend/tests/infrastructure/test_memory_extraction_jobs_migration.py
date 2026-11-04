"""Candidate queue upgrades preserve existing memories and enforce one lease per story."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text, inspect, event
from sqlalchemy.exc import IntegrityError
import core.database as database


class ExtractionJobMigrationTests(unittest.TestCase):
    def test_upgrade_downgrade_preserves_memories_and_enforces_processing_lease(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine("sqlite:///" + (Path(directory) / "jobs.db").as_posix())

            @event.listens_for(engine, "connect")
            def foreign_keys(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")

            config = Config()
            config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
            try:
                with patch.object(database, "engine", engine):
                    command.upgrade(config, "a2b3c4d5e6f7")
                    with engine.begin() as connection:
                        for statement in (
                            "INSERT INTO characters (id,name,description,first_mes) VALUES (1,'fixture','test','hello')",
                            "INSERT INTO sessions (id,title) VALUES (1,'story')",
                            "INSERT INTO session_personas (id,session_id,character_id) VALUES (1,1,1)",
                            "INSERT INTO memory_chunks (id,persona_id,content,memory_type) VALUES (1,1,'old','fact')",
                        ):
                            connection.execute(text(statement))
                    command.upgrade(config, "head")
                    with engine.begin() as connection:
                        for mid in (1, 2, 3):
                            connection.execute(text("INSERT INTO chat_messages (id,session_id,role,content,is_active) VALUES (:id,1,'user','fixture',1)"), {"id": mid})
                        connection.execute(text("UPDATE session_personas SET last_summarized_msg_id=3 WHERE id=1"))
                        connection.execute(text("INSERT INTO memory_extraction_jobs (persona_id,kind,payload_json,status) VALUES (1,'candidates',:payload,'processing')"),
                                           {"payload": '{"sources":[{"id":2},{"id":3}]}'})
                    with self.assertRaises(IntegrityError), engine.begin() as connection:
                        connection.execute(text("INSERT INTO memory_extraction_jobs (persona_id,kind,payload_json,status) VALUES (1,'candidates','{}','processing')"))
                    command.downgrade(config, "a2b3c4d5e6f7")
                    self.assertNotIn("memory_extraction_jobs", inspect(engine).get_table_names())
                    with engine.connect() as connection:
                        self.assertEqual([("old",)], list(connection.execute(text("SELECT content FROM memory_chunks"))))
                        self.assertEqual(1, connection.execute(text("SELECT last_summarized_msg_id FROM session_personas WHERE id=1")).scalar())
                    command.upgrade(config, "head")
                    with engine.begin() as connection:
                        connection.execute(text("INSERT INTO memory_extraction_jobs (persona_id,kind,payload_json) VALUES (1,'candidates','{}')"))
                        connection.execute(text("DELETE FROM session_personas WHERE id=1"))
                        self.assertEqual(0, connection.execute(text("SELECT count(*) FROM memory_extraction_jobs")).scalar())
                        self.assertEqual([], list(connection.execute(text("PRAGMA foreign_key_check"))))
            finally:
                engine.dispose()
