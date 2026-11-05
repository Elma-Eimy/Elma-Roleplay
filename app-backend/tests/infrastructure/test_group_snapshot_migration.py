"""快照表升级保留旧库；来源删除不清理快照，降级不能静默丢数据。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
import core.database as database
from core.models import GroupPersonaOrigin, GroupInheritedMemorySnapshot


class GroupSnapshotMigrationTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.engine = create_engine("sqlite:///" + (Path(directory.name) / "fixture.db").as_posix())
        self.addCleanup(self.engine.dispose)
        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        self.config = Config()
        self.config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
        engine_patch = patch.object(database, "engine", self.engine)
        engine_patch.start()
        self.addCleanup(engine_patch.stop)
        command.upgrade(self.config, "a7b8c9d0e1f2")
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO characters (id,name,description,first_mes) VALUES (1,'fixture','test','hello')"))
            connection.execute(text("INSERT INTO sessions (id,title,kind) VALUES (1,'source','single'),(2,'group','group')"))
            connection.execute(text("INSERT INTO session_personas (id,session_id,character_id,member_slot) VALUES (10,1,1,0),(20,2,1,1)"))
            connection.execute(text("INSERT INTO memory_chunks (id,persona_id,content,memory_type) VALUES (1,10,'saved','fact')"))
        command.upgrade(self.config, "a8b9c0d1e2f3")
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO group_persona_origins (persona_id,mode,captured_at,initial_state_json,source_session_id,source_persona_id,content_fingerprint) VALUES (20,'single_snapshot',CURRENT_TIMESTAMP,'{}',1,10,'fixture')"))
            connection.execute(text("INSERT INTO group_inherited_memory_snapshots (persona_id,content,memory_type,temporal_status,source_memory_id,source_persona_id,source_session_id,captured_at,content_fingerprint) VALUES (20,'frozen','fact','unknown',1,10,1,CURRENT_TIMESTAMP,'fixture')"))

    def test_tables_match_orm_and_source_deletion_preserves_audit_and_content(self):
        for model in (GroupPersonaOrigin, GroupInheritedMemorySnapshot):
            self.assertEqual(set(model.__table__.columns.keys()),
                             {col["name"] for col in inspect(self.engine).get_columns(model.__tablename__)})
            foreign_keys = inspect(self.engine).get_foreign_keys(model.__tablename__)
            self.assertEqual([(["persona_id"], "session_personas")],
                             [(fk["constrained_columns"], fk["referred_table"]) for fk in foreign_keys])
        constraints = inspect(self.engine).get_unique_constraints("group_inherited_memory_snapshots")
        self.assertEqual(["persona_id", "source_memory_id"], constraints[0]["column_names"])
        with self.engine.begin() as connection:
            self.assertEqual("saved", connection.execute(text("SELECT content FROM memory_chunks WHERE id=1")).scalar())
            connection.execute(text("DELETE FROM sessions WHERE id=1"))
            self.assertEqual((1, 10), connection.execute(text("SELECT source_session_id,source_persona_id FROM group_persona_origins")).one())
            self.assertEqual("frozen", connection.execute(text("SELECT content FROM group_inherited_memory_snapshots")).scalar())
            self.assertEqual([], connection.exec_driver_sql("PRAGMA foreign_key_check").all())
            connection.execute(text("DELETE FROM sessions WHERE id=2"))
            self.assertEqual(0, connection.execute(text("SELECT COUNT(*) FROM group_persona_origins")).scalar())
            self.assertEqual(0, connection.execute(text("SELECT COUNT(*) FROM group_inherited_memory_snapshots")).scalar())

    def test_downgrade_refuses_saved_snapshots_then_allows_empty_tables(self):
        with self.assertRaisesRegex(RuntimeError, "存在群聊来源快照"):
            command.downgrade(self.config, "a7b8c9d0e1f2")
        with self.engine.begin() as connection:
            self.assertEqual("a8b9c0d1e2f3", connection.execute(text("SELECT version_num FROM alembic_version")).scalar())
            self.assertEqual("frozen", connection.execute(text("SELECT content FROM group_inherited_memory_snapshots")).scalar())
            connection.execute(text("DELETE FROM sessions WHERE id=2"))
        command.downgrade(self.config, "a7b8c9d0e1f2")
        self.assertNotIn("group_persona_origins", inspect(self.engine).get_table_names())
        command.upgrade(self.config, "head")
        with self.engine.connect() as connection:
            self.assertEqual("saved", connection.execute(text("SELECT content FROM memory_chunks WHERE id=1")).scalar())
            self.assertEqual([], connection.exec_driver_sql("PRAGMA foreign_key_check").all())
