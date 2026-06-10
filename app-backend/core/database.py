import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from core.config import settings

# 确保数据库路径绝对化，避免不同入口启动时数据库位置发生偏移
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

db_path = settings.STORAGE_SQLITE_DB_PATH
if not os.path.isabs(db_path):
    db_path = os.path.join(BASE_DIR, db_path)

# 确保数据库所在的父目录存在，避免 SQLite 启动报错
db_dir = os.path.dirname(db_path)
if db_dir:
    os.makedirs(db_dir, exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{db_path}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, connect_args={"check_same_thread": False}
)

# SQLite 每次连接都需要显式开启外键约束和 WAL 模式
@event.listens_for(engine, "connect")
def _set_sqlite_pragma(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys = ON")   # 强制外键约束（CASCADE 等才能生效）
    cursor.execute("PRAGMA journal_mode = WAL")  # 提升并发读写性能
    cursor.close()

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def run_migrations(db_engine):
    from sqlalchemy import inspect, text
    inspector = inspect(db_engine)
    if 'chat_messages' not in inspector.get_table_names():
        return
    columns = [col['name'] for col in inspector.get_columns('chat_messages')]
    
    with db_engine.begin() as conn:
        if 'parent_id' not in columns:
            try:
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN parent_id INTEGER REFERENCES chat_messages(id) ON DELETE CASCADE"))
                print("[MIGRATION] Successfully added parent_id to chat_messages.")
            except Exception as e:
                print(f"[MIGRATION] Error adding parent_id: {e}")
        if 'is_active' not in columns:
            try:
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN is_active BOOLEAN NOT NULL DEFAULT 1"))
                print("[MIGRATION] Successfully added is_active to chat_messages.")
            except Exception as e:
                print(f"[MIGRATION] Error adding is_active: {e}")
        if 'audio_path' not in columns:
            try:
                conn.execute(text("ALTER TABLE chat_messages ADD COLUMN audio_path VARCHAR(255) NULL"))
                print("[MIGRATION] Successfully added audio_path to chat_messages.")
            except Exception as e:
                print(f"[MIGRATION] Error adding audio_path: {e}")

try:
    run_migrations(engine)
except Exception as e:
    print(f"[WARN] Auto migration failed: {e}")
