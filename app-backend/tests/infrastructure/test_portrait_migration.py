"""已有故事升级与降级保留原消息，资源 ID 不复用。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text, inspect
import core.database as database


class PortraitMigrationTests(unittest.TestCase):
    def test_upgrade_downgrade_preserves_existing_story(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine("sqlite:///" + (Path(directory) / "portraits.db").as_posix())
            config = Config()
            config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
            try:
                with patch.object(database, "engine", engine):
                    command.upgrade(config, "c8d9e0f1a2b3")
                    with engine.begin() as connection:
                        connection.execute(text("INSERT INTO characters (id,name,description,first_mes) VALUES (1,'fixture','test','hello')"))
                        connection.execute(text("INSERT INTO sessions (id,title) VALUES (1,'old story')"))
                        connection.execute(text("INSERT INTO session_personas (id,session_id,character_id) VALUES (1,1,1)"))
                        connection.execute(text("INSERT INTO chat_messages (id,session_id,role,content,is_active) VALUES (1,1,'assistant','original',1)"))
                    command.upgrade(config, "head")
                    with engine.begin() as connection:
                        self.assertEqual(0, connection.execute(text("SELECT portrait_base FROM session_personas")).scalar())
                        self.assertIsNone(connection.execute(text("SELECT portrait_selection FROM chat_messages")).scalar())
                        insert = text("INSERT INTO character_portraits (character_id,name,image_path) VALUES (1,'image','test.png')")
                        connection.execute(insert)
                        old = connection.execute(text("SELECT id FROM character_portraits")).scalar()
                        connection.execute(text("DELETE FROM character_portraits"))
                        connection.execute(insert)
                        self.assertGreater(connection.execute(text("SELECT id FROM character_portraits")).scalar(), old)
                    command.downgrade(config, "c8d9e0f1a2b3")
                    self.assertNotIn("character_portraits", inspect(engine).get_table_names())
                    with engine.connect() as connection:
                        self.assertEqual("original", connection.execute(text("SELECT content FROM chat_messages")).scalar())
                        self.assertEqual([], connection.execute(text("PRAGMA foreign_key_check")).all())
                    command.upgrade(config, "head")
            finally:
                engine.dispose()
