"""v1 原文和权限回填、组合约束、级联与无损降级。"""
import unittest

from alembic import command
from sqlalchemy import event, inspect, text
from sqlalchemy.exc import IntegrityError

from core.models import GroupRoundCandidate, GroupContentUnit, GroupUnitVisibility, GroupDirectorStep
from tests.infrastructure import test_group_round_migration as fixtures

HEAD = "b0d1e2f3a4b5"
OLD = fixtures.HEAD


class GroupUnitsMigrationTests(unittest.TestCase):
    def setUp(self):
        fixtures.GroupRoundMigrationTests.setUp(self)
        command.upgrade(self.config, OLD)
        fixtures.GroupRoundMigrationTests.seed(self)

    snapshot = fixtures.GroupRoundMigrationTests.snapshot

    def test_populated_upgrade_preserves_unicode_text_state_and_exact_permissions(self):
        original = self.snapshot()
        with self.engine.begin() as db:
            db.execute(text("UPDATE group_rounds SET user_content=:value WHERE id=1"), {"value": "😀\x00原文"})
            db.execute(text("UPDATE group_content_visibility SET decision='hidden' WHERE item_id=2"))
        command.upgrade(self.config, HEAD)
        self.assertEqual(original, self.snapshot())
        with self.engine.connect() as db:
            self.assertEqual([(1, "user", 0, 4, None), (2, "legacy", None, None, "saved")],
                db.execute(text("SELECT item_id,kind,source_start,source_end,text FROM group_content_units ORDER BY item_id")).all())
            self.assertEqual([(20, "visible"), (20, "hidden")], db.execute(text(
                "SELECT recipient_persona_id,decision FROM group_unit_visibility ORDER BY unit_id")).all())
            self.assertEqual(0, db.execute(text("SELECT count(*) FROM group_director_steps")).scalar())
            self.assertEqual([], db.exec_driver_sql("PRAGMA foreign_key_check").all())
        command.downgrade(self.config, OLD)
        with self.engine.connect() as db:
            self.assertEqual("😀\x00原文", db.execute(text("SELECT user_content FROM group_rounds WHERE id=1")).scalar())
            self.assertEqual("hidden", db.execute(text("SELECT decision FROM group_content_visibility WHERE item_id=2")).scalar())

    def test_schema_matches_orm_for_units_audit_and_new_candidate_columns(self):
        command.upgrade(self.config, HEAD)
        inspector = inspect(self.engine)
        for model in (GroupRoundCandidate, GroupContentUnit, GroupUnitVisibility, GroupDirectorStep):
            table = model.__table__
            self.assertEqual(set(table.columns.keys()), {row["name"] for row in inspector.get_columns(table.name)})
            self.assertEqual({tuple(c.column_keys) for c in table.foreign_key_constraints},
                {tuple(c["constrained_columns"]) for c in inspector.get_foreign_keys(table.name)})
            self.assertEqual({tuple(c.columns.keys()) for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"},
                {tuple(c["column_names"]) for c in inspector.get_unique_constraints(table.name)})
        checks = {row["name"] for row in inspector.get_check_constraints("group_round_candidates")}
        self.assertTrue({"ck_group_protocol_version", "ck_group_finish_reason"} <= checks)

    def test_cross_candidate_cross_group_and_malformed_audit_are_rejected(self):
        command.upgrade(self.config, HEAD)
        statements = (
            "UPDATE group_content_units SET candidate_id=2 WHERE item_id=1",
            "UPDATE group_content_units SET session_id=3 WHERE item_id=1",
            "UPDATE group_unit_visibility SET recipient_persona_id=30 WHERE unit_id=1",
            "UPDATE group_content_units SET source_end=-1 WHERE item_id=1",
            "UPDATE group_round_candidates SET protocol_version=3 WHERE id=1",
            "UPDATE group_round_candidates SET finish_reason='failed' WHERE id=1",
            "INSERT INTO group_director_steps(candidate_id,session_id,stage,step_index,expected_revision,result_revision,item_id,decision_json,model,policy_version) "
                "VALUES(2,3,'user_visibility',1,0,1,1,'{}','fixture',2)",
            "INSERT INTO group_director_steps(candidate_id,session_id,stage,step_index,expected_revision,result_revision,item_id,decision_json,model,policy_version) "
                "VALUES(1,2,'next_action',1,0,2,1,'{}','fixture',2)",
        )
        for sql in statements:
            with self.subTest(sql=sql), self.assertRaises(IntegrityError):
                with self.engine.begin() as db:
                    db.execute(text(sql))

    def test_downgrade_refuses_v2_or_audit_or_terminal_data_and_cascade_cleans_all(self):
        command.upgrade(self.config, HEAD)
        for field in ("protocol_version=2", "finish_reason='step_limit'"):
            with self.engine.begin() as db:
                db.execute(text("UPDATE group_round_candidates SET " + field + " WHERE id=1"))
            with self.assertRaisesRegex(RuntimeError, "拒绝有损降级"):
                command.downgrade(self.config, OLD)
            with self.engine.begin() as db:
                db.execute(text("UPDATE group_round_candidates SET protocol_version=1,finish_reason=NULL WHERE id=1"))
        with self.engine.begin() as db:
            db.execute(text("INSERT INTO group_director_steps(candidate_id,session_id,stage,step_index,expected_revision,result_revision,item_id,decision_json,model,policy_version) "
                "VALUES(1,2,'user_visibility',1,0,1,1,'{}','fixture',2)"))
        with self.assertRaisesRegex(RuntimeError, "拒绝有损降级"):
            command.downgrade(self.config, OLD)
        with self.engine.begin() as db:
            db.execute(text("DELETE FROM sessions WHERE id IN (2,3)"))
            for table in ("group_content_units", "group_unit_visibility", "group_director_steps"):
                self.assertEqual(0, db.execute(text("SELECT count(*) FROM " + table)).scalar())
            self.assertEqual("saved", db.execute(text("SELECT content FROM memory_chunks WHERE id=1")).scalar())
        command.downgrade(self.config, OLD)

    def test_failed_upgrade_rolls_back_columns_backfill_and_revision(self):
        def fail(connection, cursor, statement, parameters, context, executemany):
            if "INSERT INTO group_unit_visibility" in statement:
                raise RuntimeError("injected backfill failure")
        event.listen(self.engine, "before_cursor_execute", fail)
        try:
            with self.assertRaisesRegex(RuntimeError, "injected backfill"):
                command.upgrade(self.config, HEAD)
        finally:
            event.remove(self.engine, "before_cursor_execute", fail)
        self.assertNotIn("group_content_units", inspect(self.engine).get_table_names())
        self.assertNotIn("protocol_version", {row["name"] for row in inspect(self.engine).get_columns("group_round_candidates")})
        with self.engine.connect() as db:
            self.assertEqual(OLD, db.execute(text("SELECT version_num FROM alembic_version")).scalar())
            self.assertEqual("saved", db.execute(text("SELECT content FROM group_content_items WHERE id=2")).scalar())
        command.upgrade(self.config, HEAD)
