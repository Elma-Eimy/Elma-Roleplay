"""M4-A 保留旧库、约束与拒绝有损降级。"""
import unittest
from alembic import command
from sqlalchemy import inspect, text, event
from sqlalchemy.exc import IntegrityError
from core.models import GroupRound, GroupRoundCandidate, GroupRoundOperation
from tests.infrastructure import test_group_units_migration as fixtures

HEAD = "b1e2f3a4b5c6"
OLD = fixtures.HEAD


class GroupOperationsMigrationTests(unittest.TestCase):
    snapshot = fixtures.GroupUnitsMigrationTests.snapshot

    def setUp(self):
        fixtures.GroupUnitsMigrationTests.setUp(self)
        command.upgrade(self.config, OLD)

    def test_upgrade_preserves_content_permissions_and_schema_matches_orm(self):
        with self.engine.connect() as db:
            before = {table: db.execute(text("SELECT * FROM " + table)).all() for table in (
                "group_content_items", "group_content_visibility", "group_content_units", "group_unit_visibility")}
        command.upgrade(self.config, HEAD)
        inspector = inspect(self.engine)
        for model in (GroupRound, GroupRoundCandidate, GroupRoundOperation):
            table = model.__table__
            self.assertEqual(set(table.columns.keys()), {c["name"] for c in inspector.get_columns(table.name)})
            self.assertEqual({tuple(c.column_keys) for c in table.foreign_key_constraints},
                             {tuple(c["constrained_columns"]) for c in inspector.get_foreign_keys(table.name)})
        with self.engine.connect() as db:
            for table, values in before.items():
                self.assertEqual(values, db.execute(text("SELECT * FROM " + table)).all())
            self.assertEqual([], db.exec_driver_sql("PRAGMA foreign_key_check").all())
            self.assertEqual([(0,), (0,), (0,)], db.execute(text("SELECT group_revision FROM sessions ORDER BY id")).all())
        command.downgrade(self.config, OLD)
        command.upgrade(self.config, HEAD)

    def test_checks_cross_round_active_unique_and_session_cascade(self):
        command.upgrade(self.config, HEAD)
        operation = "INSERT INTO group_round_operations(session_id,round_id,candidate_id,client_request_id,kind,status,request_fingerprint,accepted_result_json) VALUES(2,1,1,'one','send','queued','hash','{}')"
        with self.engine.begin() as db:
            db.execute(text(operation))
            db.execute(text("INSERT INTO group_rounds(id,session_id,round_index,user_content,confirmed_at) VALUES(3,2,2,'other round',CURRENT_TIMESTAMP)"))
            db.execute(text("INSERT INTO group_round_candidates(id,round_id,session_id) VALUES(3,3,2)"))
        for sql in (
            "UPDATE sessions SET group_revision=-1 WHERE id=2",
            "UPDATE group_rounds SET confirmed_at=CURRENT_TIMESTAMP,discarded_at=CURRENT_TIMESTAMP WHERE id=1",
            "UPDATE group_round_operations SET candidate_id=2 WHERE id=1",
            "UPDATE group_round_operations SET candidate_id=3 WHERE id=1",
            "UPDATE group_round_operations SET round_id=2 WHERE id=1",
            "UPDATE group_round_operations SET session_id=3 WHERE id=1",
            "UPDATE group_round_operations SET call_count=-1 WHERE id=1",
            "UPDATE group_round_candidates SET checkpoint='unknown' WHERE id=1",
            operation.replace("'one'", "'two'"),
            operation.replace("'queued'", "'succeeded'"),
        ):
            with self.subTest(sql=sql), self.assertRaises(IntegrityError):
                with self.engine.begin() as db:
                    db.execute(text(sql))
        with self.engine.begin() as db:
            db.execute(text("DELETE FROM sessions WHERE id=2"))
            self.assertEqual(0, db.execute(text("SELECT count(*) FROM group_round_operations")).scalar())
            self.assertEqual([], db.exec_driver_sql("PRAGMA foreign_key_check").all())

    def test_downgrade_refuses_each_new_data_shape(self):
        command.upgrade(self.config, HEAD)
        for table, field, reset in (
            ("sessions", "group_revision=1", "group_revision=0"),
            ("group_rounds", "discarded_at=CURRENT_TIMESTAMP", "discarded_at=NULL"),
            ("group_round_candidates", "checkpoint='user_visibility'", "checkpoint=NULL"),
            ("group_round_candidates", "call_snapshot_json='{}'", "call_snapshot_json=NULL"),
            ("group_round_candidates", "provider_fingerprint='hash'", "provider_fingerprint=NULL"),
        ):
            with self.engine.begin() as db:
                db.execute(text("UPDATE " + table + " SET " + field))
            with self.assertRaisesRegex(RuntimeError, "拒绝有损降级"):
                command.downgrade(self.config, OLD)
            with self.engine.begin() as db:
                db.execute(text("UPDATE " + table + " SET " + reset))
        with self.engine.begin() as db:
            db.execute(text("INSERT INTO group_round_operations(session_id,round_id,candidate_id,client_request_id,kind,status,request_fingerprint,accepted_result_json) VALUES(2,1,1,'one','discard','succeeded','hash','{}')"))
        with self.assertRaisesRegex(RuntimeError, "拒绝有损降级"):
            command.downgrade(self.config, OLD)

    def test_failed_upgrade_rolls_back_columns_indexes_and_revision(self):
        def fail(connection, cursor, statement, parameters, context, executemany):
            if "CREATE TABLE group_round_operations" in statement:
                raise RuntimeError("injected operation failure")
        event.listen(self.engine, "before_cursor_execute", fail)
        try:
            with self.assertRaisesRegex(RuntimeError, "injected"):
                command.upgrade(self.config, HEAD)
        finally:
            event.remove(self.engine, "before_cursor_execute", fail)
        self.assertNotIn("group_revision", {c["name"] for c in inspect(self.engine).get_columns("sessions")})
        with self.engine.connect() as db:
            self.assertEqual(OLD, db.execute(text("SELECT version_num FROM alembic_version")).scalar())
            self.assertEqual([], db.exec_driver_sql("PRAGMA foreign_key_check").all())
