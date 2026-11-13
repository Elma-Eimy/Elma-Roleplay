"""旧库不回填业务调度，新增表约束、事务回滚和有损降级保护。"""
import unittest

from alembic import command
from sqlalchemy import event, inspect
from sqlalchemy.exc import IntegrityError
from core.models import GroupDispatch, GroupRoundCandidate
from tests.infrastructure import test_group_units_migration as fixtures

OLD = 'b8a9b0c1d2e3'
HEAD = 'b9b0c1d2e3f4'


class GroupDispatchMigrationTests(unittest.TestCase):
    snapshot = fixtures.GroupUnitsMigrationTests.snapshot

    def setUp(self):
        fixtures.GroupUnitsMigrationTests.setUp(self)
        command.upgrade(self.config, OLD)

    def test_upgrade_preserves_legacy_data_and_matches_orm_without_backfill(self):
        tables = ('group_content_items', 'group_content_visibility', 'group_content_units',
                  'group_unit_visibility', 'group_director_steps')
        with self.engine.connect() as db:
            before = {table: db.exec_driver_sql('SELECT * FROM ' + table).all() for table in tables}
        command.upgrade(self.config, HEAD)
        inspector = inspect(self.engine)
        for model in (GroupDispatch, GroupRoundCandidate):
            self.assertEqual(set(model.__table__.columns.keys()),
                             {row['name'] for row in inspector.get_columns(model.__tablename__)})
            self.assertEqual({tuple(fk.column_keys) for fk in model.__table__.foreign_key_constraints},
                             {tuple(fk['constrained_columns']) for fk in inspector.get_foreign_keys(model.__tablename__)})
        with self.engine.connect() as db:
            for table, rows in before.items():
                self.assertEqual(rows, db.exec_driver_sql('SELECT * FROM ' + table).all())
            self.assertEqual([(0,), (0,)], db.exec_driver_sql('SELECT dispatch_version FROM group_round_candidates ORDER BY id').all())
            self.assertEqual(0, db.exec_driver_sql('SELECT count(*) FROM group_dispatches').scalar())
            self.assertEqual([], db.exec_driver_sql('PRAGMA foreign_key_check').all())
        command.downgrade(self.config, OLD)
        self.assertNotIn('group_dispatches', inspect(self.engine).get_table_names())
        self.assertNotIn('dispatch_version', {row['name'] for row in inspect(self.engine).get_columns('group_round_candidates')})

    def test_foreign_keys_revision_checks_uniqueness_and_session_cascade(self):
        command.upgrade(self.config, HEAD)
        insert = ("INSERT INTO group_dispatches(candidate_id,session_id,sequence,speaker_persona_id,"
                  "response_reference,reason_code,expected_revision,result_revision) "
                  "VALUES(1,2,2,20,'item:1','follow_up',1,2)")
        invalid = (
            insert.replace('VALUES(1,2,2,20', 'VALUES(2,2,2,20'),
            insert.replace('VALUES(1,2,2,20', 'VALUES(1,2,2,30'),
            insert.replace('VALUES(1,2,2,20', 'VALUES(1,2,0,20'),
            insert.replace("'follow_up',1,2", "'unknown',1,2"),
            insert.replace("'follow_up',1,2", "'follow_up',1,3"),
            'UPDATE group_round_candidates SET dispatch_version=2 WHERE id=1',
        )
        for sql in invalid:
            with self.subTest(sql=sql), self.assertRaises(IntegrityError), self.engine.begin() as db:
                db.exec_driver_sql(sql)
        with self.engine.begin() as db:
            db.exec_driver_sql(insert)
        for sql in (insert, 'UPDATE group_dispatches SET completed_revision=2'):
            with self.subTest(sql=sql), self.assertRaises(IntegrityError), self.engine.begin() as db:
                db.exec_driver_sql(sql)
        with self.engine.begin() as db:
            db.exec_driver_sql('DELETE FROM sessions WHERE id=2')
            self.assertEqual(0, db.exec_driver_sql('SELECT count(*) FROM group_dispatches').scalar())
            self.assertEqual([], db.exec_driver_sql('PRAGMA foreign_key_check').all())

    def test_new_candidate_marker_and_dispatch_each_block_lossy_downgrade(self):
        command.upgrade(self.config, HEAD)
        with self.engine.begin() as db:
            db.exec_driver_sql('UPDATE group_round_candidates SET dispatch_version=1 WHERE id=1')
        with self.assertRaisesRegex(RuntimeError, '拒绝有损降级'):
            command.downgrade(self.config, OLD)
        with self.engine.begin() as db:
            db.exec_driver_sql('UPDATE group_round_candidates SET dispatch_version=0 WHERE id=1')
            db.exec_driver_sql("INSERT INTO group_dispatches(candidate_id,session_id,sequence,speaker_persona_id,"
                "reason_code,expected_revision,result_revision) VALUES(1,2,2,20,'follow_up',1,2)")
        with self.assertRaisesRegex(RuntimeError, '拒绝有损降级'):
            command.downgrade(self.config, OLD)
        with self.engine.connect() as db:
            self.assertEqual(HEAD, db.exec_driver_sql('SELECT version_num FROM alembic_version').scalar())
            self.assertEqual(1, db.exec_driver_sql('SELECT count(*) FROM group_dispatches').scalar())

    def test_failed_upgrade_rolls_back_new_column_table_and_revision(self):
        def fail(connection, cursor, statement, parameters, context, executemany):
            if 'CREATE TABLE group_dispatches' in statement:
                raise RuntimeError('injected dispatch migration failure')
        event.listen(self.engine, 'before_cursor_execute', fail)
        try:
            with self.assertRaisesRegex(RuntimeError, 'injected dispatch'):
                command.upgrade(self.config, HEAD)
        finally:
            event.remove(self.engine, 'before_cursor_execute', fail)
        self.assertNotIn('dispatch_version', {row['name'] for row in inspect(self.engine).get_columns('group_round_candidates')})
        self.assertNotIn('group_dispatches', inspect(self.engine).get_table_names())
        with self.engine.connect() as db:
            self.assertEqual(OLD, db.exec_driver_sql('SELECT version_num FROM alembic_version').scalar())
            self.assertEqual([], db.exec_driver_sql('PRAGMA foreign_key_check').all())
