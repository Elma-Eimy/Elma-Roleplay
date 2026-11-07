"""把群聊向量索引重建登记到当前配置库的 Outbox。"""
from core.database import SessionLocal
from core.models import OutboxJob


if __name__ == "__main__":
    with SessionLocal() as db:
        db.add(OutboxJob(task_type="rebuild_group_index", payload="{}"))
        db.commit()
    print("已登记群聊向量索引重建，后台将从 SQLite 重新索引。")
