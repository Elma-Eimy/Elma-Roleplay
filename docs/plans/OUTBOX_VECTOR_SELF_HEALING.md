# Outbox 向量同步空 ID 排查记录

记录 2026-11-05 线上服务的重复退避异常，以及 2026-11-18 完成的代码修复。

## 问题背景与现场

线上 `roleplay-backend.service` 出现后台 Outbox Worker 持续重试报警：
- **涉及任务**：Job #7, #15, #21, #27, #35, #41（类型均为 `upsert_vector`）。
- **异常信息**：
  ```text
  ValueError: Expected ID to be a str, got None in upsert.
  ```
- **现场原因**：
  1. 对应记忆（ID 804, 812, 818, 824, 832, 838）在 SQLite `memory_chunks` 数据表中的 `chroma_doc_id` 字段值为 `NULL`。
  2. [`outbox_worker.py`](../../app-backend/services/infrastructure/outbox_worker.py) 的 `handle_upsert_vector` 中，正常写入路径直接使用了 `ids=[chunk.chroma_doc_id]`，向 ChromaDB 传入了 `[None]` 从而引发校验异常。
  3. 虽然 Outbox Job 的 payload 中已持久化了初始文档 ID（如 `{"chroma_doc_id": "mem_804"}`），但该函数仅在 `chunk is None`（记忆已被物理删除）的分支中使用了 fallback，未在 `chunk.chroma_doc_id` 为空时做兜底降级。

线上数据已于当时的排查中补齐，重试积压也已清理。

## 修复结果

Worker 处理仍在队列中的同步任务时会补齐缺失的文档 ID。提交顺序和删除规则见 [后端架构](../architecture/BACKEND.md#后台任务)，回归用例见 [向量 Outbox 一致性测试](../../app-backend/tests/infrastructure/test_vector_outbox_consistency.py)。
