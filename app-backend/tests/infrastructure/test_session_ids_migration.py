"""已迁移的会话继续保留内容、引用及分配过的编号。"""
import unittest

from alembic import command
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from tests.infrastructure import test_group_operations_migration as fixtures


class SessionIdsMigrationTests(unittest.TestCase):
    snapshot = fixtures.GroupOperationsMigrationTests.snapshot

    def test_populated_upgrade_preserves_rows_and_prevents_id_reuse(self):
        fixtures.GroupOperationsMigrationTests.setUp(self)
        command.upgrade(self.config, fixtures.HEAD)
        self.old_tables = inspect(self.engine).get_table_names()
        before = self.snapshot()

        command.upgrade(self.config, "b2f3a4b5c6d7")
        self.assertEqual(before, self.snapshot())
        with self.engine.begin() as db:
            self.assertEqual([], db.exec_driver_sql("PRAGMA foreign_key_check").all())
            with self.assertRaises(IntegrityError):
                db.exec_driver_sql("UPDATE sessions SET group_revision=-1 WHERE id=2")
            insert = "INSERT INTO sessions(kind) VALUES ('group')"
            old_id = db.exec_driver_sql(insert).lastrowid
            db.exec_driver_sql("DELETE FROM sessions WHERE id = ?", (old_id,))
            new_id = db.exec_driver_sql(insert).lastrowid
            self.assertGreater(new_id, old_id)
            db.exec_driver_sql("DELETE FROM sessions WHERE id = ?", (new_id,))

        command.downgrade(self.config, fixtures.HEAD)
        self.assertEqual(before, self.snapshot())
        command.downgrade(self.config, fixtures.OLD)
