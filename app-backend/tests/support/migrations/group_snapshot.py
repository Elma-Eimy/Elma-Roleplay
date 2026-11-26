"""群聊迁移测试共用旧库与快照。"""
import tempfile
from pathlib import Path
from unittest.mock import patch
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, event, text
import core.database as database


class GroupSnapshotMigrationFixture:
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.engine = create_engine("sqlite:///" + (Path(directory.name) / "fixture.db").as_posix())
        self.addCleanup(self.engine.dispose)
        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")
        self.config = Config()
        self.config.set_main_option("script_location", str(Path(__file__).resolve().parents[3] / "alembic"))
        engine_patch = patch.object(database, "engine", self.engine)
        engine_patch.start()
        self.addCleanup(engine_patch.stop)
        command.upgrade(self.config, "a7b8c9d0e1f2")
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO characters (id,name,description,first_mes) VALUES (1,'fixture','test','hello')"))
            connection.execute(text("INSERT INTO sessions (id,title,kind) VALUES (1,'source','single'),(2,'group','group')"))
            connection.execute(text("INSERT INTO session_personas (id,session_id,character_id,member_slot) VALUES (10,1,1,0),(20,2,1,1)"))
            connection.execute(text("INSERT INTO memory_chunks (id,persona_id,content,memory_type) VALUES (1,10,'saved','fact')"))
        command.upgrade(self.config, "a8b9c0d1e2f3")
        with self.engine.begin() as connection:
            connection.execute(text("INSERT INTO group_persona_origins (persona_id,mode,captured_at,initial_state_json,source_session_id,source_persona_id,content_fingerprint) VALUES (20,'single_snapshot',CURRENT_TIMESTAMP,'{}',1,10,'fixture')"))
            connection.execute(text("INSERT INTO group_inherited_memory_snapshots (persona_id,content,memory_type,temporal_status,source_memory_id,source_persona_id,source_session_id,captured_at,content_fingerprint) VALUES (20,'frozen','fact','unknown',1,10,1,CURRENT_TIMESTAMP,'fixture')"))
