"""
数据库清理脚本 — 重置 SQLite 和 ChromaDB 中的所有数据

用法：python clear_db.py
"""

import os
import shutil
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.database import engine
from core import models
from core.config import settings


def clear_databases():
    print("=" * 55)
    print("⚠️  警告: 此操作将删除 SQLite 和 ChromaDB 中的所有数据！")
    print("=" * 55)
    confirm = input("确定要清空数据库吗？(y/n): ")
    if confirm.lower() != 'y':
        print("操作已取消。")
        return

    # 1. 清空 SQLite 数据库
    db_name = os.path.basename(settings.STORAGE_SQLITE_DB_PATH)
    print(f"\n[1/2] 正在清空 SQLite 数据库 ({db_name})...")
    try:
        models.Base.metadata.drop_all(bind=engine)
        models.Base.metadata.create_all(bind=engine)
        print("  ✅ SQLite 数据库已成功重置。")
        print("     重建的表: characters, sessions, session_personas, memory_chunks, chat_messages")
    except Exception as e:
        print(f"  ❌ SQLite 重置失败: {e}")
        print("     如果提示文件被占用，请先停止 uvicorn 服务器。")

    # 2. 清空 ChromaDB
    print("\n[2/2] 正在清空 ChromaDB 向量数据库...")
    chroma_path = settings.STORAGE_CHROMA_DB_PATH
    if os.path.exists(chroma_path):
        try:
            shutil.rmtree(chroma_path)
            print("  ✅ ChromaDB 数据目录已成功删除。")
        except Exception as e:
            print(f"  ❌ ChromaDB 清除失败: {e}")
            print("     如果提示文件被占用，请确保已停止 uvicorn 服务器。")
    else:
        print("  ⚠️ ChromaDB 数据目录不存在，跳过。")

    print("\n🎉 清理完成！可以重新运行服务器了。")


if __name__ == "__main__":
    clear_databases()
