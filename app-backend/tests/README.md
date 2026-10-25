# 后端测试

自动回归按职责分组，沿用标准库 `unittest`。使用当前后端虚拟环境，在 `app-backend/` 目录执行命令。

## 自动回归

`memory/test_memory_extraction_jobs.py` 覆盖外部调用无事务、独立写入、失败隔离与幂等恢复、时间补全、来源独立失效、无新聊天的捕获重试与真实接口状态。`infrastructure/test_memory_extraction_jobs_migration.py` 验证升级回退、唯一处理租约和级联清理；`test_memory_retry_worker.py` 验证关闭时等待工作线程释放资源。

`memory/test_memory_event_buffer.py` 覆盖跨批次事件、事实与承诺直接写入、手动收尾、重启、图谱与 Outbox 原子回滚、来源和分叉边界；`infrastructure/test_memory_event_buffer_migration.py` 验证旧库升级、回退和外键清理。

事件边界回归还覆盖长片段不丢正文、情绪超长时独立保留、容量收尾的完整跨卡依据及失效、未落库依赖拒绝发布和非法下标安全处理。

`memory/test_memory_card_extraction.py` 覆盖写入专用召回、向量未同步时的批内语义去重、低重要性旧卡、分叉与时间边界、关系判断失败回滚及重试，使用本地模型和向量替身。

`memory/test_joint_retrieval.py` 验证语义种子扩图、支持卡回查、去重、摘要映射、预算和故事边界；`test_memory_fact_semantics.py` 验证提纯时间语义及整理保留。`infrastructure/test_memory_fact_migration.py` 使用临时库验证共源字段升降级，不读取开发数据。

```bash
# 全部自动回归
python -m tests

# 只运行一个领域
python -m tests --group memory

# 只运行一个测试模块
python -m tests --group conversation --pattern test_branch_context_boundary.py
```

Windows 未激活虚拟环境时，可将命令中的 `python` 替换为 `.\venv\Scripts\python.exe`。

统一入口会将源码和自动测试复制到临时目录，生成测试配置、占位凭据、头像夹具，并迁移临时 SQLite 数据库，再运行测试。ChromaDB 和音频目录也位于临时目录；不复制开发用的 `.env`、`config.yaml`、数据库或媒体。子进程结束后清理临时目录，发现失败或没有匹配测试时返回非零退出码。

`core/test_migration_logging.py` 在该临时副本的独立进程中配置 Uvicorn 日志，再执行真实应用内迁移；验证重复迁移不改变宿主日志状态，整理 INFO 诊断仍能输出。它使用现有源码与 Alembic 复制范围，不读取开发库。

测试使用内存/临时数据库以及模型和向量服务替身。新增自动测试时也应遵循这一约定，不调用真实服务。

CHARX 专项：`python -m tests --group parsing --pattern test_charx_import.py` 覆盖非法 JSON、ZIP/图片预算、GIF/APNG/WebP 多帧原字节保留与帧数限制、设定合并/开场选择/独立世界书同步、事务回滚、幂等回执和共享图片回收。上传鉴权/流量限制及迁移分别见 `infrastructure/test_charx_upload.py`、`infrastructure/test_charx_migration.py`。

## 目录

| 目录 | 范围 |
| --- | --- |
| `api/` | 应用装配与生命周期、路由契约、记忆导航、最近会话、鉴权以及路由与服务边界 |
| `conversation/` | 分叉边界、Prompt、模型参数、对话回合和上下文交接 |
| `memory/` | 记忆提纯、版本替代、整理的原子性/撤销/分支快照、离线检索和图谱质量 |
| `infrastructure/` | Alembic、头像清理、音频缓存恢复、Embedding 失败和 Outbox 一致性 |
| `core/` | 配置加载与持久化 |
| `lorebook/` | 世界书触发与兼容规则 |
| `parsing/` | 回复标签解析 |
| `tts/` | 语音文本预处理 |
| `manual/` | 旧式场景脚本、真实服务抽查与本地文件检查，只显式运行 |

## 手动场景

这些脚本保留原先的行为，统一使用 `manual_*.py` 命名，不参与默认自动发现。例如：

```bash
python -m tests.manual.manual_deepseek_memory_quality
python -m tests.manual.manual_lorebook
```

`manual_api`、`manual_branching_start_message`、`manual_closed_loop_memory`、`manual_delete_candidate`、`manual_graph_rag`、`manual_independent_lorebook`、`manual_memory_deduplication`、`manual_outbox` 会使用当前配置的数据库或服务，其中包含写入和删除。`manual_tts_api` 和 `manual_deepseek_memory_quality` 会调用真实模型；`manual_parse` 仍依赖脚本指定的本地角色卡路径。执行前先阅读脚本，并使用独立测试配置与数据。

`manual_lorebook` 是尚未转为 `unittest` 的规则检查脚本；将它保留在这里不表示它需要真实模型。

## 新增与调试

`memory/test_memory_quality_tool.py` 覆盖质量验收工具的隔离启动、固定回放、指标边界、HTML 转义和在线凭据替身，不调用真实模型；样本为 `tests/fixtures/memory_quality_cases.json`。人工审阅用法见 [记忆整理质量验收](../../docs/MEMORY_QUALITY.md)。

`memory/test_graph_memory_consistency.py` 覆盖图谱消息与记忆证据、追加版本、分叉隔离、原数组下标关联、`same/replace`、人工修改/删除、整理后证据保留及原子回滚；`infrastructure/test_graph_evidence_migration.py` 验证旧库升降级保留原行且不猜测来源。优先使用隔离入口，不直接运行会写当前库的 `manual/manual_graph_rag.py`。

自动测试使用 `test_*.py` 命名，放到对应领域目录。测试包的 `__init__.py` 保持轻量，公共夹具按实际复用需求提取，避免在包导入时修改应用配置或启动服务。

需要保留现场或使用 IDE 单步调试时，可在准备好独立配置的数据环境中直接运行标准入口，例如 `python -m unittest tests.memory.test_memory_versioning -v`。直接运行 `unittest` 会跳过上述临时工作区隔离。
