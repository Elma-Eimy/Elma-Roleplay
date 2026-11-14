# Outbox 向量同步容错与自愈待办

记录 2026-11-05 线上服务排查发现的 Outbox Worker 重复退避异常、根本原因与后续代码加固待办。

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

线上数据已于排查时修复补齐并清空重试堆积，此待办专注于代码层面的长效防固。

## 待处理事项（Action Items）

### 1. `outbox_worker.py` 兜底与自愈
- **目标文件**：`app-backend/services/infrastructure/outbox_worker.py` 中的 `handle_upsert_vector`
- **改造要点**：
  - 提取目标文档 ID：`doc_id = chunk.chroma_doc_id or fallback_doc_id or f"mem_{chunk.id}"`
  - 若 `chunk.chroma_doc_id` 为空，执行自愈回写：
    ```python
    if not chunk.chroma_doc_id:
        chunk.chroma_doc_id = doc_id
        db.commit()
    ```
  - 传递给 `collection.upsert(ids=[doc_id], ...)`，杜绝 `[None]` 传递给向量库。

### 2. `memory_manager.py` 写入事务防御
- **目标文件**：`app-backend/services/memory/memory_manager.py` 中的 `add_memory_chunk`
- **改造要点**：
  - 在 `chunk.chroma_doc_id = chroma_doc_id` 赋值后立即执行 `db.flush()`。
  - 避免外部在 `auto_commit=False` 模式（例如批量提取、整理）下，因后续缺少更新刷盘导致某些记录的 `chroma_doc_id` 留存为 `NULL`。

### 3. 回归测试用例
- **目标文件**：`app-backend/tests/infrastructure/test_vector_outbox_consistency.py`
- **测试场景**：
  - 新增测试用例 `test_upsert_heals_null_chroma_doc_id_from_fallback`：
  - 构造一条 SQLite 中 `chroma_doc_id` 为 `None` 的 `MemoryChunk`，但其 Outbox Job payload 包含有效 `chroma_doc_id`；
  - 运行 worker 任务，断言向量库写入成功、SQLite 记录被自动修复为对应 ID、Outbox 任务正常完成被删除。
