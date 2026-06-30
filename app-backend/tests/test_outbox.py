"""
发件箱模式 (Outbox Pattern) 单元测试脚本
"""

import os
import sys
import io
import json
import unittest
from unittest.mock import patch, MagicMock
from datetime import datetime, timedelta

# 强制在 Windows 终端下使用 UTF-8 编码输出以支持 Emoji 和中文
if sys.platform.startswith('win'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 将当前目录的父目录加入 python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SessionLocal
from core import Base, engine
from core.models import OutboxJob, OutboxJobStatus
from services.outbox_worker import process_pending_jobs, execute_job


def run_outbox_test():
    print("=" * 60)
    print("🚀 开始运行发件箱模式 Outbox Pattern 单元测试...")
    print("=" * 60)

    # 1. 初始化数据库表结构
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # 清理已存在的任务以确保测试干净
    db.query(OutboxJob).delete()
    db.commit()

    try:
        # ── 测试 1: 写入任务并验证 ──
        print("\n[测试 1] 验证发件箱任务入库...")
        test_payload = {"character_id": 999, "doc_ids": ["doc_1", "doc_2"]}
        job = OutboxJob(
            task_type="delete_vector",
            payload=json.dumps(test_payload),
            run_after=datetime.now()
        )
        db.add(job)
        db.commit()

        # 检查数据库中是否存在该任务
        db_job = db.query(OutboxJob).filter(OutboxJob.task_type == "delete_vector").first()
        assert db_job is not None, "❌ 错误: 任务未成功存入 SQLite!"
        assert json.loads(db_job.payload)["character_id"] == 999
        print("  ✅ 任务入库成功！")

        # ── 测试 2: 验证任务成功处理并自动物理删除 ──
        print("\n[测试 2] 验证任务成功执行与自动清理...")
        mock_collection = MagicMock()
        
        # 使用 patch 模拟 ChromaDB 获取 collection
        with patch("services.memory_manager.get_character_collection", return_value=mock_collection) as mock_get_col:
            # 运行 worker 任务处理器
            import asyncio
            asyncio.run(process_pending_jobs())
            
            # 验证 ChromaDB 的 delete 被调用
            mock_collection.delete.assert_called_once_with(ids=["doc_1", "doc_2"])
            print("  ✅ 成功触发 ChromaDB 对应删除操作！")

            # 验证已完成的任务被成功物理删除以清理数据库
            remaining_jobs = db.query(OutboxJob).count()
            assert remaining_jobs == 0, f"❌ 错误: 执行成功的任务应被物理删除，当前仍有 {remaining_jobs} 个任务"
            print("  ✅ 执行完成的任务已被成功物理删除，无数据库垃圾！")

        # ── 测试 3: 验证任务执行失败与指数退避重试 ──
        print("\n[测试 3] 验证任务执行失败的重试和退避调度...")
        fail_job = OutboxJob(
            task_type="delete_vector",
            payload=json.dumps(test_payload),
            run_after=datetime.now()
        )
        db.add(fail_job)
        db.commit()

        with patch("services.memory_manager.get_character_collection", side_effect=Exception("ChromaDB Connection Timeout")) as mock_fail_col:
            asyncio.run(process_pending_jobs())

            # 再次查询该任务的状态
            db_failed_job = db.query(OutboxJob).first()
            assert db_failed_job is not None, "❌ 错误: 失败的任务不应该被删除"
            assert db_failed_job.status == OutboxJobStatus.failed, f"❌ 错误: 状态应为 failed，当前为 {db_failed_job.status}"
            assert db_failed_job.attempts == 1, f"❌ 错误: 尝试次数应为 1，当前为 {db_failed_job.attempts}"
            assert "ChromaDB Connection Timeout" in db_failed_job.last_error, "❌ 错误: 未正确记录异常日志"
            
            # 验证下一次运行时间是否已经向后推迟了
            time_diff = db_failed_job.run_after - datetime.now()
            # 第一次失败的 backoff 时间为 15 * (2^1) = 30 秒左右
            assert time_diff.total_seconds() > 10, f"❌ 错误: 指数退避的调度时间不够合理: {time_diff.total_seconds()}秒"
            print(f"  ✅ 任务失败处理成功，自动进行退避调度，下次执行延迟: {time_diff.total_seconds():.1f} 秒")

    finally:
        # 清理测试数据
        db.query(OutboxJob).delete()
        db.commit()
        db.close()
        print("\n🎉 发件箱模式 Outbox Pattern 单元测试全部通过！")


if __name__ == "__main__":
    run_outbox_test()
