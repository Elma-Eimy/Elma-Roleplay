"""群聊召回的 SQLite 触发器，同时供迁移和隔离库建表使用。"""

SNAPSHOT_INSERT = """
INSERT INTO group_recall_cards(persona_id,snapshot_id)
SELECT persona_id,id FROM group_inherited_memory_snapshots
"""
CAPTURE_INSERT = """
INSERT INTO group_recall_cards(persona_id,capture_id,slot,replaces_id)
SELECT c.persona_id,c.id,j.key,json_extract(j.value,'$.replaces_id')
FROM group_memory_captures AS c, json_each(c.cards_json) AS j
WHERE c.cards_json IS NOT NULL
"""
SYNC = """
INSERT INTO outbox_jobs(task_type,payload,status,attempts,max_attempts,run_after)
VALUES ('sync_group_card',json_object('id',%s.id),'pending',0,5,CURRENT_TIMESTAMP);
"""

TRIGGERS = {
    "group_recall_snapshot": ("AFTER INSERT ON group_inherited_memory_snapshots",
                              SNAPSHOT_INSERT + " WHERE id=NEW.id;"),
    "group_recall_capture_insert": ("AFTER INSERT ON group_memory_captures WHEN NEW.cards_json IS NOT NULL",
                                    CAPTURE_INSERT + " AND c.id=NEW.id;"),
    "group_recall_capture_update": ("AFTER UPDATE OF cards_json ON group_memory_captures WHEN OLD.cards_json IS NOT NEW.cards_json",
                                    "DELETE FROM group_recall_cards WHERE capture_id=NEW.id;" +
                                    CAPTURE_INSERT + " AND c.id=NEW.id;"),
    "group_recall_sync": ("AFTER INSERT ON group_recall_cards", SYNC % "NEW"),
    "group_recall_delete": ("AFTER DELETE ON group_recall_cards", SYNC % "OLD"),
}


def install_triggers(connection):
    for name, (event, body) in TRIGGERS.items():
        connection.exec_driver_sql(f"CREATE TRIGGER IF NOT EXISTS {name} {event} BEGIN {body} END")
