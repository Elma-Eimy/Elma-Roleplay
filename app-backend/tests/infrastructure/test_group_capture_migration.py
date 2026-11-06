"""升级不自动重放旧轮次，任务防串群且随群删除。"""
import unittest
from alembic import command
from sqlalchemy.exc import IntegrityError
from tests.infrastructure import test_group_operations_migration as fixtures


class GroupCaptureMigrationTests(unittest.TestCase):
    snapshot = fixtures.GroupOperationsMigrationTests.snapshot

    def test_upgrade_preserves_data_and_scopes_captures(self):
        fixtures.GroupOperationsMigrationTests.setUp(self)
        command.upgrade(self.config, "b2f3a4b5c6d7")
        before = self.snapshot()
        command.upgrade(self.config, "b3a4b5c6d7e8")
        self.assertEqual(before, self.snapshot())
        insert = "INSERT INTO group_memory_captures(session_id,round_id,candidate_id,persona_id) VALUES (2,1,1,?)"
        with self.engine.begin() as db:
            self.assertEqual(0, db.exec_driver_sql("SELECT count(*) FROM group_memory_captures").scalar())
            with self.assertRaises(IntegrityError):
                db.exec_driver_sql(insert, (30,))
            db.exec_driver_sql(insert, (20,))
            with self.assertRaises(IntegrityError):
                db.exec_driver_sql(insert, (20,))
        with self.assertRaisesRegex(RuntimeError, "拒绝有损降级"):
            command.downgrade(self.config, "b2f3a4b5c6d7")
        with self.engine.begin() as db:
            db.exec_driver_sql("DELETE FROM sessions WHERE id=2")
            self.assertEqual(0, db.exec_driver_sql("SELECT count(*) FROM group_memory_captures").scalar())
            self.assertEqual([], db.exec_driver_sql("PRAGMA foreign_key_check").all())
        command.downgrade(self.config, "b2f3a4b5c6d7")
