"""群聊轮次迁移保留旧值，以组合外键拒绝跨群引用。"""
import unittest
import warnings

from alembic import command
from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.exc import IntegrityError, SAWarning

from core.models import Base, GroupRound, GroupRoundCandidate, GroupContentItem, GroupContentVisibility
from tests.infrastructure import test_group_snapshot_migration as fixtures

HEAD = "a9c0d1e2f3a4"
OLD = "a8b9c0d1e2f3"
TABLES = ("group_rounds", "group_round_candidates", "group_content_items", "group_content_visibility")


class GroupRoundMigrationTests(unittest.TestCase):
    def setUp(self):
        fixtures.GroupSnapshotMigrationTests.setUp(self)
        self.old_tables = inspect(self.engine).get_table_names()
        self.original = self.snapshot()

    def snapshot(self):
        with self.engine.connect() as db:
            return {table: db.execute(text('SELECT * FROM "' + table + '" ORDER BY 1')).all()
                    for table in self.old_tables if table != "alembic_version"}

    def seed(self):
        with self.engine.begin() as db:
            for sql in (
                "INSERT INTO sessions(id,kind) VALUES(3,'group')",
                "INSERT INTO session_personas(id,session_id,character_id,member_slot) VALUES(30,3,1,1)",
                "INSERT INTO group_rounds(id,session_id,round_index,user_content) VALUES(1,2,1,'user'),(2,3,1,'other')",
                "INSERT INTO group_round_candidates(id,round_id,session_id) VALUES(1,1,2),(2,2,3)",
                "UPDATE group_rounds SET selected_candidate_id=id",
                "INSERT INTO group_content_items(id,candidate_id,session_id,sequence,kind) VALUES(1,1,2,0,'user')",
                "INSERT INTO group_content_items(id,candidate_id,session_id,sequence,kind,speaker_persona_id,content) VALUES(2,1,2,1,'utterance',20,'saved')",
                "INSERT INTO group_content_visibility(item_id,recipient_persona_id,session_id,decision) VALUES(1,20,2,'visible'),(2,20,2,'visible')",
            ):
                db.execute(text(sql))

    def test_upgrade_matches_orm_and_empty_downgrade_preserves_all_existing_data(self):
        command.upgrade(self.config, HEAD)
        self.assertEqual(self.original, self.snapshot())
        inspector = inspect(self.engine)
        for model in (GroupRound, GroupRoundCandidate, GroupContentItem, GroupContentVisibility):
            table = model.__table__
            historical_columns = set(table.columns.keys()) - ({"protocol_version", "finish_reason"} if model is GroupRoundCandidate else set())
            self.assertEqual(historical_columns, {c["name"] for c in inspector.get_columns(table.name)})
            self.assertEqual({tuple(c.columns.keys()) for c in table.constraints if c.__class__.__name__ == "UniqueConstraint"},
                             {tuple(c["column_names"]) for c in inspector.get_unique_constraints(table.name)})
            self.assertEqual({str(c.sqltext) for c in table.constraints if c.__class__.__name__ == "CheckConstraint"},
                             {c["sqltext"] for c in inspector.get_check_constraints(table.name)})
            self.assertEqual({tuple(c.column_keys) for c in table.foreign_key_constraints},
                             {tuple(c["constrained_columns"]) for c in inspector.get_foreign_keys(table.name)})
        command.downgrade(self.config, OLD)
        self.assertEqual(self.original, self.snapshot())
        self.assertFalse(set(TABLES) & set(inspect(self.engine).get_table_names()))
        command.upgrade(self.config, HEAD)
        with self.engine.connect() as db:
            self.assertEqual([], db.exec_driver_sql("PRAGMA foreign_key_check").all())
            self.assertEqual(1, db.exec_driver_sql("PRAGMA foreign_keys").scalar())

    def test_orm_cycle_retains_selected_foreign_key_and_supports_test_teardown(self):
        engine = create_engine("sqlite://")
        self.addCleanup(engine.dispose)
        Base.metadata.create_all(engine)
        selected = [fk for fk in inspect(engine).get_foreign_keys("group_rounds")
                    if fk["name"] == "fk_group_round_selected"]
        self.assertEqual(["selected_candidate_id", "id", "session_id"], selected[0]["constrained_columns"])
        with warnings.catch_warnings():
            warnings.simplefilter("error", SAWarning)
            Base.metadata.drop_all(engine)

    def test_failed_upgrade_rolls_back_indexes_tables_and_revision(self):
        def fail(connection, cursor, statement, parameters, context, executemany):
            if "CREATE TABLE group_content_items" in statement:
                raise RuntimeError("injected schema failure")
        event.listen(self.engine, "before_cursor_execute", fail)
        try:
            with self.assertRaisesRegex(RuntimeError, "injected schema"):
                command.upgrade(self.config, HEAD)
        finally:
            event.remove(self.engine, "before_cursor_execute", fail)
        self.assertEqual(self.original, self.snapshot())
        self.assertEqual(set(self.old_tables), set(inspect(self.engine).get_table_names()))
        self.assertNotIn("uq_sessions_id_kind", {i["name"] for i in inspect(self.engine).get_indexes("sessions")})
        with self.engine.connect() as db:
            self.assertEqual(OLD, db.execute(text("SELECT version_num FROM alembic_version")).scalar())
        command.upgrade(self.config, HEAD)

    def test_composite_constraints_reject_cross_group_and_cross_round_even_without_services(self):
        command.upgrade(self.config, HEAD)
        self.seed()
        invalid = (
            "INSERT INTO group_rounds(session_id,round_index,user_content) VALUES(1,1,'single')",
            "UPDATE group_rounds SET selected_candidate_id=2 WHERE id=1",
            "INSERT INTO group_round_candidates(round_id,session_id,version) VALUES(1,3,2)",
            "INSERT INTO group_content_items(candidate_id,session_id,sequence,kind,speaker_persona_id,content) VALUES(1,3,2,'utterance',30,'cross candidate')",
            "UPDATE group_content_items SET speaker_persona_id=30 WHERE id=2",
            "UPDATE group_content_visibility SET recipient_persona_id=30 WHERE item_id=1",
            "UPDATE group_content_visibility SET session_id=3 WHERE item_id=1",
            "INSERT INTO group_rounds(session_id,round_index,user_content) VALUES(2,2,'second pending')",
            "INSERT INTO group_round_candidates(round_id,session_id,version) VALUES(1,2,1)",
            "UPDATE group_round_candidates SET status='invalid' WHERE id=1",
            "UPDATE group_content_items SET content='duplicate user text' WHERE id=1",
            "UPDATE group_content_items SET sequence=0 WHERE id=2",
            "UPDATE group_content_visibility SET decision='public' WHERE item_id=1",
        )
        for sql in invalid:
            with self.subTest(sql=sql):
                with self.assertRaises(IntegrityError):
                    with self.engine.begin() as db:
                        db.execute(text(sql))
        with self.engine.connect() as db:
            self.assertEqual([], db.exec_driver_sql("PRAGMA foreign_key_check").all())
        with self.engine.begin() as db:
            db.execute(text("UPDATE group_rounds SET confirmed_at=CURRENT_TIMESTAMP WHERE id=1"))
            db.execute(text("INSERT INTO group_rounds(id,session_id,round_index,user_content) VALUES(3,2,2,'same group')"))
            db.execute(text("INSERT INTO group_round_candidates(id,round_id,session_id) VALUES(3,3,2)"))
        with self.assertRaises(IntegrityError):
            with self.engine.begin() as db:
                db.execute(text("UPDATE group_rounds SET selected_candidate_id=3 WHERE id=1"))

    def test_selected_cycle_cascades_and_nonempty_downgrade_cannot_discard_content(self):
        command.upgrade(self.config, HEAD)
        self.seed()
        with self.assertRaisesRegex(RuntimeError, "存在群聊轮次"):
            command.downgrade(self.config, OLD)
        with self.engine.begin() as db:
            self.assertEqual(HEAD, db.execute(text("SELECT version_num FROM alembic_version")).scalar())
            self.assertEqual("saved", db.execute(text("SELECT content FROM group_content_items WHERE id=2")).scalar())
            db.execute(text("DELETE FROM sessions WHERE id IN (2,3)"))
            for name in TABLES:
                self.assertEqual(0, db.execute(text("SELECT count(*) FROM " + name)).scalar())
            self.assertEqual("saved", db.execute(text("SELECT content FROM memory_chunks WHERE id=1")).scalar())
            self.assertEqual([], db.exec_driver_sql("PRAGMA foreign_key_check").all())
        command.downgrade(self.config, OLD)
