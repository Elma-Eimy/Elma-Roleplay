"""Graph evidence upgrades preserve legacy data without inventing provenance."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text, inspect, event
import core.database as database


class GraphEvidenceMigrationTests(unittest.TestCase):
    def test_upgrade_downgrade_preserves_legacy_graph_and_story(self):
        with tempfile.TemporaryDirectory() as directory:
            engine = create_engine("sqlite:///" + (Path(directory) / "graph.db").as_posix())
            @event.listens_for(engine, "connect")
            def foreign_keys(connection, _):
                connection.execute("PRAGMA foreign_keys=ON")
            config = Config()
            config.set_main_option("script_location", str(Path(__file__).resolve().parents[2] / "alembic"))
            try:
                with patch.object(database, "engine", engine):
                    command.upgrade(config, "a6b7c8d9e0f1")
                    with engine.begin() as connection:
                        for statement in (
                            "INSERT INTO characters (id,name,description,first_mes) VALUES (1,'fixture','test','hello')",
                            "INSERT INTO sessions (id,title) VALUES (1,'old story')",
                            "INSERT INTO session_personas (id,session_id,character_id) VALUES (1,1,1)",
                            "INSERT INTO chat_messages (id,session_id,role,content,is_active) VALUES (1,1,'assistant','original',1)",
                            "INSERT INTO graph_entities (id,persona_id,name,entity_type,description) VALUES (1,1,'fixture','person','legacy description')",
                            "INSERT INTO graph_relations (id,persona_id,source_id,target_id,relation_type,description) VALUES (1,1,1,1,'legacy','legacy relation')",
                        ):
                            connection.execute(text(statement))
                    command.upgrade(config, "head")
                    with engine.begin() as connection:
                        self.assertIsNone(connection.execute(text("SELECT evidence_json FROM graph_relations")).scalar())
                        self.assertIsNone(connection.execute(text("SELECT source_message_id_bound FROM graph_entities")).scalar())
                        self.assertEqual(0, connection.execute(text("SELECT is_stub FROM graph_entities")).scalar())
                        connection.execute(text("UPDATE graph_relations SET evidence_json='{}',source_message_id_bound=1"))
                    command.downgrade(config, "a6b7c8d9e0f1")
                    self.assertNotIn("evidence_json", [c["name"] for c in inspect(engine).get_columns("graph_entities")])
                    with engine.connect() as connection:
                        self.assertEqual("legacy relation", connection.execute(text("SELECT description FROM graph_relations")).scalar())
                        self.assertEqual("legacy description", connection.execute(text("SELECT description FROM graph_entities")).scalar())
                        self.assertEqual("original", connection.execute(text("SELECT content FROM chat_messages")).scalar())
                        self.assertEqual([], connection.execute(text("PRAGMA foreign_key_check")).all())
                    command.upgrade(config, "head")
            finally:
                engine.dispose()
