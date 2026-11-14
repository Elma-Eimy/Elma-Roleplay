"""立绘快照迁移保留旧候选，非空快照拒绝有损降级。"""
import unittest
from alembic import command
from sqlalchemy import inspect
from tests.infrastructure import test_group_operations_migration as fixtures


class GroupPortraitMigrationTests(unittest.TestCase):
    snapshot = fixtures.GroupOperationsMigrationTests.snapshot
    def setUp(self):
        fixtures.GroupOperationsMigrationTests.setUp(self)
        command.upgrade(self.config, 'b6e7f8a9b0c1')

    def test_upgrade_preserves_old_rows_and_allows_empty_downgrade(self):
        with self.engine.connect() as db:
            old = db.exec_driver_sql('SELECT id,round_id,session_id,status,revision FROM group_round_candidates').all()
        command.upgrade(self.config, 'b7f8a9b0c1d2')
        with self.engine.connect() as db:
            self.assertEqual(old, db.exec_driver_sql('SELECT id,round_id,session_id,status,revision FROM group_round_candidates').all())
            self.assertTrue(all(row[0] is None for row in db.exec_driver_sql('SELECT portrait_selections_json FROM group_round_candidates')))
            self.assertEqual([], db.exec_driver_sql('PRAGMA foreign_key_check').all())
        command.downgrade(self.config, 'b6e7f8a9b0c1')
        self.assertNotIn('portrait_selections_json', {c['name'] for c in inspect(self.engine).get_columns('group_round_candidates')})

    def test_nonempty_snapshots_refuse_lossy_downgrade(self):
        command.upgrade(self.config, 'b7f8a9b0c1d2')
        with self.engine.begin() as db:
            db.exec_driver_sql("UPDATE group_round_candidates SET portrait_selections_json='{}' WHERE id=1")
        with self.assertRaisesRegex(RuntimeError, '拒绝有损降级'):
            command.downgrade(self.config, 'b6e7f8a9b0c1')
        with self.engine.connect() as db:
            self.assertEqual('{}', db.exec_driver_sql('SELECT portrait_selections_json FROM group_round_candidates WHERE id=1').scalar())
            self.assertEqual([], db.exec_driver_sql('PRAGMA foreign_key_check').all())
