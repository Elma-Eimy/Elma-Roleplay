"""升级不自动重放旧轮次，任务防串群且随群删除。"""
import unittest
from alembic import command
from sqlalchemy.exc import IntegrityError
from tests.infrastructure import test_group_operations_migration as fixtures


class GroupCaptureMigrationTests(unittest.TestCase):
    snapshot = fixtures.GroupOperationsMigrationTests.snapshot

    def test_insights_upgrade_preserves_old_cards_and_candidate_boundary(self):
        fixtures.GroupOperationsMigrationTests.setUp(self)
        command.upgrade(self.config, "b3a4b5c6d7e8")
        with self.engine.begin() as db:
            db.exec_driver_sql("INSERT INTO group_memory_captures(session_id,round_id,candidate_id,persona_id,cards_json) "
                               "VALUES (2,1,1,20,'[]')")
        command.upgrade(self.config, "b4c5d6e7f8a9")
        with self.engine.begin() as db:
            self.assertIsNone(db.exec_driver_sql("SELECT insight_watermark FROM group_round_candidates WHERE id=1").scalar_one())
            self.assertEqual("[]", db.exec_driver_sql("SELECT cards_json FROM group_memory_captures").scalar_one())
            db.exec_driver_sql("INSERT INTO group_member_insights(capture_id,kind,content,ref,quote) "
                               "VALUES (1,'user','开始相信','1:0','我亲眼看到')")
        with self.assertRaisesRegex(RuntimeError, "拒绝有损降级"):
            command.downgrade(self.config, "b3a4b5c6d7e8")
        with self.engine.begin() as db:
            db.exec_driver_sql("DELETE FROM sessions WHERE id=2")
            self.assertEqual(0, db.exec_driver_sql("SELECT count(*) FROM group_member_insights").scalar())
        command.downgrade(self.config, "b3a4b5c6d7e8")

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

    def test_recall_migration_backfills_completed_card_and_cascades_its_index_job(self):
        fixtures.GroupOperationsMigrationTests.setUp(self)
        command.upgrade(self.config, "b4c5d6e7f8a9")
        with self.engine.begin() as db:
            db.exec_driver_sql("INSERT INTO group_memory_captures(session_id,round_id,candidate_id,persona_id,cards_json) "
                               """VALUES (2,1,1,20,'[{"content":"old card","memory_type":"fact","temporal_status":"current"}]')""")
        command.upgrade(self.config, "b5d6e7f8a9b0")
        with self.engine.begin() as db:
            card_id,slot = db.exec_driver_sql("SELECT id,slot FROM group_recall_cards WHERE capture_id=1").one()
            self.assertEqual(0,slot)
            query = "SELECT count(*) FROM outbox_jobs WHERE task_type='sync_group_card' AND json_extract(payload,'$.id')=?"
            self.assertEqual(1,db.exec_driver_sql(query,(card_id,)).scalar())
            db.exec_driver_sql("DELETE FROM group_memory_captures WHERE id=1")
            self.assertEqual(0,db.exec_driver_sql("SELECT count(*) FROM group_recall_cards WHERE id=?",(card_id,)).scalar())
            self.assertEqual(2,db.exec_driver_sql(query,(card_id,)).scalar())
