"""开场迁移不回填旧群聊，已有开场拒绝有损降级。"""
import unittest
from alembic import command
from sqlalchemy import inspect
from tests.infrastructure import test_group_snapshot_migration as fixtures


class GroupGreetingMigrationTests(unittest.TestCase):
    def setUp(self):
        fixtures.GroupSnapshotMigrationTests.setUp(self)
        command.upgrade(self.config, 'b7f8a9b0c1d2')

    def test_old_origin_preserved_without_automatic_greeting_and_empty_downgrade(self):
        with self.engine.connect() as db:
            old = db.exec_driver_sql('SELECT persona_id,initial_state_json,content_fingerprint FROM group_persona_origins').all()
        command.upgrade(self.config, 'head')
        with self.engine.connect() as db:
            self.assertEqual(old, db.exec_driver_sql('SELECT persona_id,initial_state_json,content_fingerprint FROM group_persona_origins').all())
            self.assertIsNone(db.exec_driver_sql('SELECT greeting_content FROM group_persona_origins').scalar())
            self.assertEqual([], db.exec_driver_sql('PRAGMA foreign_key_check').all())
        command.downgrade(self.config, 'b7f8a9b0c1d2')
        self.assertNotIn('greeting_content', {c['name'] for c in inspect(self.engine).get_columns('group_persona_origins')})

    def test_nonempty_opening_blocks_lossy_downgrade(self):
        command.upgrade(self.config, 'head')
        with self.engine.begin() as db:
            db.exec_driver_sql("UPDATE group_persona_origins SET greeting_content='frozen opening'")
        with self.assertRaisesRegex(RuntimeError, '拒绝有损降级'):
            command.downgrade(self.config, 'b7f8a9b0c1d2')
        with self.engine.connect() as db:
            self.assertEqual('frozen opening', db.exec_driver_sql('SELECT greeting_content FROM group_persona_origins').scalar())
