"""群聊迁移测试共用旧库与快照。"""
from sqlalchemy import inspect, text
from tests.support.migrations import group_snapshot as fixtures

HEAD = "a9c0d1e2f3a4"

OLD = "a8b9c0d1e2f3"


class GroupRoundMigrationFixture:
    def setUp(self):
        fixtures.GroupSnapshotMigrationFixture.setUp(self)
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
