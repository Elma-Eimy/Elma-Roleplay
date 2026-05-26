import os
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker

from core.config import settings

# 确保数据库路径绝对化，避免不同入口启动时数据库位置发生偏移
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

db_path = settings.STORAGE_SQLITE_DB_PATH
if not os.path.isabs(db_path):
    db_path = os.path.join(BASE_DIR, db_path)

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
