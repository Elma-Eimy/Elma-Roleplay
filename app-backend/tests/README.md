# 后端测试

自动回归按职责分组，沿用标准库 `unittest`。使用当前后端虚拟环境，在 `app-backend/` 目录执行命令。

## 自动回归

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

测试使用内存/临时数据库以及模型和向量服务替身。新增自动测试时也应遵循这一约定，不调用真实服务。

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

自动测试使用 `test_*.py` 命名，放到对应领域目录。测试包的 `__init__.py` 保持轻量，公共夹具按实际复用需求提取，避免在包导入时修改应用配置或启动服务。

需要保留现场或使用 IDE 单步调试时，可在准备好独立配置的数据环境中直接运行标准入口，例如 `python -m unittest tests.memory.test_memory_versioning -v`。直接运行 `unittest` 会跳过上述临时工作区隔离。
