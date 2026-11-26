"""快照表升级保留旧库；来源删除不清理快照，降级不能静默丢数据。"""
import unittest

from alembic import command
from sqlalchemy import inspect, text
from core.models import GroupPersonaOrigin, GroupInheritedMemorySnapshot


from tests.support.migrations.group_snapshot import GroupSnapshotMigrationFixture


class GroupSnapshotMigrationTests(GroupSnapshotMigrationFixture, unittest.TestCase):
    def test_tables_match_orm_and_source_deletion_preserves_audit_and_content(self):
        for model in (GroupPersonaOrigin, GroupInheritedMemorySnapshot):
            self.assertEqual(set(model.__table__.columns.keys()) - ({"greeting_content"} if model is GroupPersonaOrigin else set()),
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
