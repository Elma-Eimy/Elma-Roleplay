"""新元信息迁移保留原立绘与剧情选择，旧数据可以升降级。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text, inspect
import core.database as database


class CharxMigrationTests(unittest.TestCase):
    def test_upgrade_and_downgrade_preserve_existing_portraits(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine("sqlite:///" + (Path(directory) / "charx.db").as_posix())
            config = Config()
            config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
            try:
                with patch.object(database, "engine", engine):
                    command.upgrade(config, "d9e0f1a2b3c4")
                    with engine.begin() as connection:
                        connection.execute(text("INSERT INTO characters (id,name,description,first_mes) VALUES (1,'old','test','hello')"))
                        connection.execute(text("INSERT INTO character_portraits (id,character_id,name,image_path) VALUES (1,1,'old image','old.png')"))
                    command.upgrade(config, "head")
                    with engine.begin() as connection:
                        self.assertIsNone(connection.execute(text("SELECT source_uri FROM character_portraits")).scalar())
                        self.assertIsNone(connection.execute(text("SELECT content_sha256 FROM character_portraits")).scalar())
                        connection.execute(text("UPDATE character_portraits SET source_type='icon',source_name='main',source_uri='embeded://image.png'"))
                        connection.execute(text("INSERT INTO character_package_imports (token,request_hash,character_id,result_json) VALUES ('token','hash',1,'{}')"))
                    command.downgrade(config, "d9e0f1a2b3c4")
                    self.assertNotIn("character_package_imports", inspect(engine).get_table_names())
                    with engine.connect() as connection:
                        self.assertEqual("old.png", connection.execute(text("SELECT image_path FROM character_portraits")).scalar())
                        self.assertEqual([], connection.execute(text("PRAGMA foreign_key_check")).all())
                    command.upgrade(config, "head")
            finally:
                engine.dispose()
