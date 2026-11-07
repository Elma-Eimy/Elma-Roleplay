"""旧卡原文与编号不变，分段不可改写且拒绝有损降级。"""
import unittest
from alembic import command
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError
from core.models import GroupRecallCard
from tests.infrastructure import test_group_operations_migration as fixtures


class GroupMemoryPartsMigrationTests(unittest.TestCase):
    snapshot=fixtures.GroupOperationsMigrationTests.snapshot

    def setUp(self):
        fixtures.GroupOperationsMigrationTests.setUp(self)
        command.upgrade(self.config,'b5d6e7f8a9b0')
        with self.engine.begin() as db:
            db.exec_driver_sql("INSERT INTO group_memory_captures(session_id,round_id,candidate_id,persona_id,cards_json) "
                """VALUES(2,1,1,20,'[{"content":"old fact","memory_type":"fact","temporal_status":"current"}]')""")

    def test_upgrade_preserves_old_cards_and_empty_column_can_downgrade(self):
        with self.engine.connect() as db:
            old=db.exec_driver_sql('SELECT id,persona_id,capture_id,slot,indexed FROM group_recall_cards').all()
        command.upgrade(self.config,'b6e7f8a9b0c1')
        self.assertEqual(set(GroupRecallCard.__table__.columns.keys()),
                         {c['name'] for c in inspect(self.engine).get_columns('group_recall_cards')})
        with self.engine.connect() as db:
            self.assertEqual(old,db.exec_driver_sql('SELECT id,persona_id,capture_id,slot,indexed FROM group_recall_cards').all())
            self.assertIsNone(db.exec_driver_sql('SELECT parts_json FROM group_recall_cards').scalar())
            self.assertEqual([],db.exec_driver_sql('PRAGMA foreign_key_check').all())
        command.downgrade(self.config,'b5d6e7f8a9b0')

    def test_parts_are_immutable_and_nonempty_metadata_refuses_downgrade(self):
        command.upgrade(self.config,'b6e7f8a9b0c1')
        with self.engine.begin() as db:
            db.exec_driver_sql("UPDATE group_recall_cards SET parts_json='[{\"start\":0,\"end\":8}]' WHERE capture_id IS NOT NULL")
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as db:
                db.exec_driver_sql('UPDATE group_recall_cards SET parts_json=NULL')
        with self.assertRaisesRegex(RuntimeError,'拒绝有损降级'):
            command.downgrade(self.config,'b5d6e7f8a9b0')
        with self.engine.begin() as db:
            db.exec_driver_sql('DELETE FROM group_memory_captures')
            self.assertEqual([],db.exec_driver_sql('PRAGMA foreign_key_check').all())
        command.downgrade(self.config,'b5d6e7f8a9b0')
