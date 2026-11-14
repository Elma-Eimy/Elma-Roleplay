"""旧库升级保留聊天数据，压缩版本随会话回收，降级仅移除新增数据。"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect
import core.database as database
from core.models import ContextCheckpoint


class ContextCompressionMigrationTests(unittest.TestCase):
    def test_upgrade_constraints_cascade_and_downgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine("sqlite:///" + (Path(directory) / "context.db").as_posix())
            config = Config()
            config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
            try:
                with patch.object(database, "engine", engine):
                    command.upgrade(config, "b9b0c1d2e3f4")
                    with engine.begin() as db:
                        db.exec_driver_sql("INSERT INTO characters(id,name,description,first_mes) VALUES(1,'test','fixture','hello')")
                        db.exec_driver_sql("INSERT INTO sessions(id,title) VALUES(1,'story')")
                        db.exec_driver_sql("INSERT INTO session_personas(id,session_id,character_id) VALUES(1,1,1)")
                        db.exec_driver_sql("INSERT INTO chat_messages(id,session_id,role,content,is_active) VALUES(1,1,'user','original',1)")
                    command.upgrade(config, "head")
                    inspector = inspect(engine)
                    self.assertEqual(set(ContextCheckpoint.__table__.columns.keys()),
                                     {item["name"] for item in inspector.get_columns("context_checkpoints")})
                    with engine.begin() as db:
                        self.assertIsNone(db.exec_driver_sql("SELECT context_base FROM session_personas").scalar())
                        self.assertEqual("original", db.exec_driver_sql("SELECT content FROM chat_messages").scalar())
                        db.exec_driver_sql("INSERT INTO context_checkpoints(session_id,source_count,source_hash,summary,model) VALUES(1,1,'hash','summary','test')")
                        db.exec_driver_sql("DELETE FROM chat_messages WHERE id=1")
                        self.assertEqual(1, db.exec_driver_sql("SELECT count(*) FROM context_checkpoints").scalar())
                    command.downgrade(config, "b9b0c1d2e3f4")
                    self.assertNotIn("context_checkpoints", inspect(engine).get_table_names())
                    self.assertNotIn("context_base", {item["name"] for item in inspect(engine).get_columns("session_personas")})
                    with engine.connect() as db:
                        self.assertEqual("story", db.exec_driver_sql("SELECT title FROM sessions").scalar())
            finally:
                engine.dispose()
