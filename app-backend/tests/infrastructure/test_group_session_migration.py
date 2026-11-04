"""验证多成员迁移保留引用，并能从表重建失败中恢复。"""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, inspect, text
import core.database as database

OLD_HEAD = "a5b6c7d8e9f0"
NEW_HEAD = "a7b8c9d0e1f2"


class GroupSessionMigrationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.engine = create_engine("sqlite:///" + (Path(self.directory.name) / "fixture.db").as_posix())
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def enable_foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        self.config = Config()
        self.config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
        self.engine_patch = patch.object(database, "engine", self.engine)
        self.engine_patch.start()
        self.addCleanup(self.engine_patch.stop)
        command.upgrade(self.config, OLD_HEAD)
        statements = [
            "INSERT INTO characters (id,name,description,first_mes) VALUES (1,'A','card','hello'),(2,'B','card','hi')",
            "INSERT INTO sessions (id,title,parent_session_id) VALUES (10,'root',NULL),(20,'branch',10)",
            "INSERT INTO session_personas (id,session_id,character_id,parent_persona_id,affection_score,cognition_state,role_state_base,portrait_base) VALUES (100,10,1,NULL,17,'known','{}',0),(200,20,1,100,19,'branch known','{}',0)",
            "INSERT INTO chat_messages (id,session_id,role,content,is_active,parent_id) VALUES (1,10,'user','hello',1,NULL),(2,10,'assistant','active',1,1),(3,10,'assistant','candidate',0,1),(4,20,'assistant','branch',1,NULL)",
            "UPDATE sessions SET fork_message_id=2 WHERE id=20",
            "UPDATE session_personas SET last_summarized_msg_id=2,last_cognition_update_msg_id=2 WHERE id=100",
            "INSERT INTO memory_event_buffers (id,persona_id,payload_json,created_at) VALUES (1,100,'{}',CURRENT_TIMESTAMP)",
            "INSERT INTO memory_chunks (id,persona_id,origin_session_id,source_start_message_id,source_message_id,source_message_id_bound,content,memory_type,event_id,chroma_doc_id) VALUES (1,100,10,1,2,2,'remember','fact',1,'mem_1')",
            "INSERT INTO memory_extraction_jobs (id,persona_id,kind,payload_json) VALUES (1,100,'capture','{}')",
            "INSERT INTO memory_consolidations (id,persona_id,status,preview_json) VALUES (1,100,'preview','{}')",
            "INSERT INTO memory_consolidation_scopes (persona_id,consolidation_id) VALUES (100,1),(200,1)",
            "INSERT INTO memory_consolidation_scans (persona_id,memory_id,fingerprint,checked_at) VALUES (100,1,'fixture',CURRENT_TIMESTAMP)",
            "INSERT INTO graph_entities (id,persona_id,name,entity_type) VALUES (1,100,'place','location'),(2,100,'friend','person')",
            "INSERT INTO graph_relations (id,persona_id,source_id,target_id,relation_type) VALUES (1,100,1,2,'knows')",
        ]
        with self.engine.begin() as connection:
            for statement in statements:
                connection.execute(text(statement))
        self.columns = {table: [c["name"] for c in inspect(self.engine).get_columns(table)]
                        for table in inspect(self.engine).get_table_names() if table != "alembic_version"}
        self.original = self.snapshot()

    def snapshot(self):
        with self.engine.connect() as connection:
            return {table: connection.execute(text(
                'SELECT ' + ','.join('"' + col + '"' for col in columns) + ' FROM "' + table + '" ORDER BY 1'
            )).all() for table, columns in self.columns.items()}

    def assert_integrity(self, revision):
        self.assertEqual(self.original, self.snapshot())
        with self.engine.connect() as connection:
            self.assertEqual([], connection.exec_driver_sql("PRAGMA foreign_key_check").all())
            self.assertEqual(1, connection.exec_driver_sql("PRAGMA foreign_keys").scalar())
            self.assertEqual(revision, connection.execute(text("SELECT version_num FROM alembic_version")).scalar())

    def test_upgrade_and_downgrade_preserve_all_old_values_and_indexes(self):
        indexes = {table: inspect(self.engine).get_indexes(table) for table in ("sessions", "session_personas")}
        command.upgrade(self.config, NEW_HEAD)
        self.assert_integrity(NEW_HEAD)
        with self.engine.connect() as connection:
            self.assertEqual([("single",), ("single",)], connection.execute(text("SELECT kind FROM sessions ORDER BY id")).all())
            self.assertEqual([(0,), (0,)], connection.execute(text("SELECT member_slot FROM session_personas ORDER BY id")).all())
        for table, expected in indexes.items():
            self.assertEqual(expected, inspect(self.engine).get_indexes(table))
        constraints = inspect(self.engine).get_unique_constraints("session_personas")
        self.assertEqual({("session_id", "member_slot"), ("session_id", "character_id")},
                         {tuple(c["column_names"]) for c in constraints})
        command.downgrade(self.config, OLD_HEAD)
        self.assert_integrity(OLD_HEAD)
        command.upgrade(self.config, NEW_HEAD)
        self.assert_integrity(NEW_HEAD)

    def test_failed_rebuild_rolls_back_ddl_data_and_revision_then_can_retry(self):
        def fail_rebuild(connection, cursor, statement, parameters, context, executemany):
            if 'ALTER TABLE _alembic_tmp_session_personas RENAME' in statement:
                raise RuntimeError("injected rebuild failure")

        event.listen(self.engine, "before_cursor_execute", fail_rebuild)
        try:
            with self.assertRaisesRegex(RuntimeError, "injected rebuild failure"):
                command.upgrade(self.config, NEW_HEAD)
        finally:
            event.remove(self.engine, "before_cursor_execute", fail_rebuild)
        self.assert_integrity(OLD_HEAD)
        self.assertNotIn("kind", [c["name"] for c in inspect(self.engine).get_columns("sessions")])
        self.assertFalse(any(name.startswith("_alembic_tmp") for name in inspect(self.engine).get_table_names()))
        command.upgrade(self.config, NEW_HEAD)
        self.assert_integrity(NEW_HEAD)

    def test_foreign_key_violation_rolls_back_migration(self):
        def corrupt_reference(connection, cursor, statement, parameters, context, executemany):
            if statement == "PRAGMA foreign_key_check":
                cursor.execute("UPDATE memory_chunks SET persona_id=9999")

        event.listen(self.engine, "before_cursor_execute", corrupt_reference)
        try:
            with self.assertRaisesRegex(RuntimeError, "外键校验失败"):
                command.upgrade(self.config, NEW_HEAD)
        finally:
            event.remove(self.engine, "before_cursor_execute", corrupt_reference)
        self.assert_integrity(OLD_HEAD)

    def test_downgrade_refuses_group_data_without_changing_anything(self):
        command.upgrade(self.config, NEW_HEAD)
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO sessions (id,title,kind) VALUES (30,'group','group')"))
            connection.execute(text("INSERT INTO session_personas (id,session_id,character_id,member_slot) VALUES (300,30,1,1),(400,30,2,2)"))
        with self.assertRaisesRegex(RuntimeError, "存在群聊数据"):
            command.downgrade(self.config, OLD_HEAD)
        with self.engine.connect() as connection:
            self.assertEqual(2, connection.execute(text("SELECT COUNT(*) FROM session_personas WHERE session_id=30")).scalar())
            self.assertEqual(NEW_HEAD, connection.execute(text("SELECT version_num FROM alembic_version")).scalar())
            self.assertEqual(1, connection.exec_driver_sql("PRAGMA foreign_keys").scalar())
