"""旧库升级保留会话与消息；降级仅移除状态列。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text, inspect, event
import core.database as database


class RoleStateMigrationTests(unittest.TestCase):
    def test_upgrade_and_downgrade_preserve_existing_story(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine("sqlite:///" + (Path(directory) / "state.db").as_posix())
            @event.listens_for(engine, "connect")
            def foreign_keys(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
            config = Config()
            config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
            try:
                with patch.object(database, "engine", engine):
                    command.upgrade(config, "f5a6b7c8d9e0")
                    with engine.begin() as connection:
                        connection.execute(text("INSERT INTO characters (id,name,description,first_mes) VALUES (1,'fixture','test','hello')"))
                        connection.execute(text("INSERT INTO sessions (id,title) VALUES (1,'old story')"))
                        connection.execute(text("INSERT INTO session_personas (id,session_id,character_id) VALUES (1,1,1)"))
                        connection.execute(text("INSERT INTO chat_messages (id,session_id,role,content,is_active) VALUES (1,1,'assistant','original',1)"))
                        connection.execute(text("INSERT INTO memory_chunks (id,persona_id,content,memory_type,source_message_id) VALUES (1,1,'memory','fact',1)"))
                    command.upgrade(config, "head")
                    with engine.begin() as connection:
                        self.assertIsNone(connection.execute(text("SELECT role_state_base FROM session_personas")).scalar())
                        self.assertEqual("original", connection.execute(text("SELECT content FROM chat_messages")).scalar())
                        connection.execute(text("UPDATE chat_messages SET role_state_patch='{}', role_state_manual='{}'"))
                    command.downgrade(config, "f5a6b7c8d9e0")
                    self.assertNotIn("role_state_patch", [column["name"] for column in inspect(engine).get_columns("chat_messages")])
                    with engine.connect() as connection:
                        self.assertEqual("original", connection.execute(text("SELECT content FROM chat_messages")).scalar())
                        self.assertEqual("memory", connection.execute(text("SELECT content FROM memory_chunks")).scalar())
                        self.assertEqual(1, connection.execute(text("SELECT source_message_id FROM memory_chunks")).scalar())
                        self.assertEqual([], connection.execute(text("PRAGMA foreign_key_check")).all())
                    command.upgrade(config, "head")
            finally:
                engine.dispose()
