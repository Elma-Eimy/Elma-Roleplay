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
    from sqlalchemy import inspect
    from alembic.config import Config
    from alembic import command
    
    inspector = inspect(db_engine)
    tables = inspector.get_table_names()
    
    alembic_cfg = Config("alembic.ini")
    
    # 如果已存在 chat_messages 但没有 alembic_version，说明是已存在的旧版数据库，对其执行 baseline stamp
    if "chat_messages" in tables and "alembic_version" not in tables:
        try:
            print("[MIGRATION] Existing database detected. Stamping with baseline revision e8c3a2d02d0f...")
            command.stamp(alembic_cfg, "e8c3a2d02d0f")
            print("[MIGRATION] Baseline stamping completed successfully.")
        except Exception as e:
            print(f"[WARN] Failed to stamp baseline revision: {e}")
            
    # 自动应用所有新迁移升级
    try:
        print("[MIGRATION] Running database upgrades...")
        command.upgrade(alembic_cfg, "head")
        print("[MIGRATION] Database upgrades completed successfully.")
    except Exception as e:
        print(f"[ERROR] Database upgrade failed: {e}")
        raise e

try:
    run_migrations(engine)
except Exception as e:
    print(f"[WARN] Auto migration failed: {e}")
