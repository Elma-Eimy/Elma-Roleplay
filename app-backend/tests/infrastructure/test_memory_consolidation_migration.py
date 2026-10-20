"""旧库升级保留来源/版本/索引，降级仅移除整理产物。"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
import core.database as database


class MemoryConsolidationMigrationTests(unittest.TestCase):
    def test_populated_old_database_upgrade_and_downgrade_preserve_original_cards(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine("sqlite:///" + (Path(directory) / "old.db").as_posix())
            @event.listens_for(engine, "connect")
            def foreign_keys(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
            config = Config()
            config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
            try:
                with patch.object(database, "engine", engine):
                    command.upgrade(config, "c2d3e4f5a6b7")
                    with engine.begin() as connection:
                        for statement in [
                            "INSERT INTO characters (id,name,description,first_mes) VALUES (1,'fixture','test','hello')",
                            "INSERT INTO sessions (id,title) VALUES (1,'old story')",
                            "INSERT INTO session_personas (id,session_id,character_id) VALUES (1,1,1)",
                            "INSERT INTO chat_messages (id,session_id,role,content) VALUES (1,1,'user','old source')",
                            "INSERT INTO memory_chunks (id,persona_id,content,memory_type,source_message_id,source_start_message_id) VALUES (1,1,'old memory','fact',1,1)",
                            "INSERT INTO memory_chunks (id,persona_id,content,memory_type,supersedes_id) VALUES (2,1,'new memory','fact',1)",
                        ]:
                            connection.execute(text(statement))
                    command.upgrade(config, "head")
                    with engine.begin() as connection:
                        self.assertEqual([(1, "old memory", 1, 1, None), (2, "new memory", None, None, 1)],
                            [tuple(row) for row in connection.execute(text("SELECT id,content,source_start_message_id,source_message_id,supersedes_id FROM memory_chunks ORDER BY id"))])
                        self.assertEqual([], connection.execute(text("PRAGMA foreign_key_check")).all())
                        self.assertEqual(1, connection.execute(text("SELECT source_message_id_bound FROM memory_chunks WHERE id=1")).scalar())
                        connection.execute(text("INSERT INTO memory_consolidations (id,persona_id,status,preview_json) VALUES (1,1,'applied','{}')"))
                        connection.execute(text("INSERT INTO memory_chunks (id,persona_id,content,memory_type,consolidation_id) VALUES (3,1,'summary','fact',1)"))
                        connection.execute(text("INSERT INTO memory_consolidation_sources (summary_id,source_id) VALUES (3,1),(3,2)"))
                        connection.execute(text("INSERT INTO memory_consolidation_scopes (persona_id,consolidation_id) VALUES (1,1)"))
                    command.downgrade(config, "c2d3e4f5a6b7")
                    with engine.connect() as connection:
                        self.assertEqual(2, connection.execute(text("SELECT COUNT(*) FROM memory_chunks")).scalar())
                        self.assertEqual([], connection.execute(text("PRAGMA foreign_key_check")).all())
                    self.assertNotIn("consolidation_id", {column["name"] for column in inspect(engine).get_columns("memory_chunks")})
                    command.upgrade(config, "head")
            finally:
                engine.dispose()

    def test_upgrade_recovers_deleted_source_cutoffs_from_first_version_snapshots(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine("sqlite:///" + (Path(directory) / "first-version.db").as_posix())
            @event.listens_for(engine, "connect")
            def foreign_keys(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
            config = Config()
            config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
            try:
                with patch.object(database, "engine", engine):
                    command.upgrade(config, "d3e4f5a6b7c8")
                    with engine.begin() as connection:
                        for statement in [
                            "INSERT INTO characters (id,name,description,first_mes) VALUES (1,'fixture','test','hello')",
                            "INSERT INTO sessions (id,title) VALUES (1,'old story')",
                            "INSERT INTO session_personas (id,session_id,character_id) VALUES (1,1,1)",
                            "INSERT INTO chat_messages (id,session_id,role,content) VALUES (10,1,'user','first'),(20,1,'user','future')",
                            "INSERT INTO memory_chunks (id,persona_id,content,memory_type,source_message_id) VALUES (1,1,'first','event',10),(2,1,'future','event',20),(4,1,'manual','fact',NULL)",
                        ]:
                            connection.execute(text(statement))
                        payload = json.dumps({"sources": [{"id": 1, "source_message_id": 10}, {"id": 2, "source_message_id": 20}]})
                        connection.execute(text("INSERT INTO memory_consolidations (id,persona_id,status,preview_json) VALUES (1,1,'applied',:payload)"), {"payload": payload})
                        connection.execute(text("INSERT INTO memory_chunks (id,persona_id,content,memory_type,source_message_id,consolidation_id) VALUES (3,1,'summary','event',20,1)"))
                        connection.execute(text("INSERT INTO memory_consolidation_sources (summary_id,source_id) VALUES (3,1),(3,2)"))
                        connection.execute(text("INSERT INTO memory_consolidation_scopes (persona_id,consolidation_id) VALUES (1,1)"))
                        connection.execute(text("DELETE FROM chat_messages WHERE id=20"))
                        self.assertIsNone(connection.execute(text("SELECT source_message_id FROM memory_chunks WHERE id=3")).scalar())
                    command.upgrade(config, "head")
                    with engine.begin() as connection:
                        self.assertEqual([(1, 10), (2, 20), (3, 20), (4, None)], [tuple(row) for row in connection.execute(text(
                            "SELECT id,source_message_id_bound FROM memory_chunks ORDER BY id"))])
                        # 边界是普通整数，不会指向已不存在的消息，也不破坏现有外键。
                        self.assertEqual([], connection.execute(text("PRAGMA foreign_key_check")).all())
                    command.downgrade(config, "d3e4f5a6b7c8")
                    with engine.connect() as connection:
                        self.assertEqual(4, connection.execute(text("SELECT COUNT(*) FROM memory_chunks")).scalar())
                    self.assertNotIn("source_message_id_bound", {col["name"] for col in inspect(engine).get_columns("memory_chunks")})
                    command.upgrade(config, "head")
                    with engine.connect() as connection:
                        self.assertEqual(20, connection.execute(text("SELECT source_message_id_bound FROM memory_chunks WHERE id=3")).scalar())
            finally:
                engine.dispose()
