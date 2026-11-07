"""记忆原文分段一旦保存便不可改写，旧候选仍按原始卡片读取。"""

TRIGGER = 'group_recall_parts_immutable'


def install_parts_trigger(connection):
    connection.exec_driver_sql(f'''CREATE TRIGGER IF NOT EXISTS {TRIGGER}
        BEFORE UPDATE OF parts_json ON group_recall_cards
        WHEN OLD.parts_json IS NOT NULL AND NEW.parts_json IS NOT OLD.parts_json
        BEGIN SELECT RAISE(ABORT, 'memory parts are immutable'); END''')
