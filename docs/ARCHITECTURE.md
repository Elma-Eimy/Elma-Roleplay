# 后端架构与职责

## 启动与请求链路

```text
main.py
  └─ application.factory.create_app()
       ├─ CORS、静态资源、鉴权依赖和路由装配
       └─ application.lifecycle.lifespan
            ├─ 启动：Alembic 升级 → 创建 Outbox 任务 → 启动提示
            └─ 关闭：取消并等待 Outbox 任务 → 清理后台对话 Worker

HTTP 请求 → routers/ → services/ → core/ 与基础设施客户端
维护命令 → scripts/ → core/ 与基础设施客户端
```

保持从 `app-backend/` 执行 `uvicorn main:app --reload`。应用工厂也可通过 `uvicorn application.factory:create_app --factory` 使用。

`create_app()` 只组装应用，不执行数据库迁移或启动 Worker。这不代表所有依赖都已延迟初始化：现有服务导入仍可能加载配置、创建数据库引擎和 ChromaDB 客户端。

## 模块边界

| 位置 | 负责 | 不应放入 |
| --- | --- | --- |
| `main.py` | 暴露 ASGI 的 `app` | 接口处理、数据查询、后台任务管理 |
| `application/` | 应用工厂、生命周期、启动提示 | 领域业务规则 |
| `routers/` | 路径、输入校验、鉴权依赖、HTTP 响应与异常转换 | 复杂查询、文件恢复和对话编排 |
| `services/conversation/` | 会话、消息、Prompt、模型执行和对话回合 | FastAPI 应用创建 |
| `services/memory/` | 记忆提纯、版本、继承、检索、图谱和管理查询 | HTTP 路由装配 |
| `services/lorebook/` | 世界书解析、触发和注入 | 服务器启动逻辑 |
| `services/media/` | 音频缓存文件查找与恢复 | HTTP 状态码与 `FileResponse` |
| `services/infrastructure/` | LLM/向量客户端、Outbox 和模型日志 | 页面展示逻辑 |
| `core/` | 配置、ORM、数据库会话、迁移函数、锁和基础工具 | 路由注册与后台任务启动 |
| `schemas.py` | 当前 Pydantic 请求模型 | ORM 表定义或数据库操作 |
| `scripts/` | 显式执行的查询和重置工具 | 自动启动的业务流程 |
| `tests/` | 自动回归和独立手动场景 | 生产业务实现 |

`character_service.py`、`parse.py` 和 `tts_service.py` 暂保留在 `services/` 根目录，分别承担角色、角色卡解析和 TTS 功能。后续可按领域继续组织，迁移时应同时更新调用方，避免保留多份实现。

`schemas.py` 当前体量较小，仍集中管理；`core/models.py` 的 ORM 关系和迁移链保持原样。数据库、头像、音频、配置和虚拟环境位置不因代码目录整理而移动。

记忆整理由 `services/memory/memory_consolidation_service.py` 编排，`memory_visibility.py` 解析消息分叉边界和故事整理快照。整理记录、来源关联与 Persona 整理范围分别持久化；新分支复制当时的整理范围，父故事后续撤销不会回写子故事。原卡保留，列表/统计/检索共享有效视图，写入沿用 Outbox。详情见 [记忆 API](api/MEMORY_API.md)。

手动增量扫描由 `memory_consolidation_scan.py` 维护原卡版本指纹；`memory_consolidation_scans` 通过 Alembic 新增，扫描进度与整理应用状态分离。先按 SQLite 有效本地原卡视图逐页比对版本，再将最多 100 张未检查/变更卡送给模型；外部调用结束后在短写事务内重新核对当前版本，并与预览原子保存。仅保存成功且版本未变的卡推进检查记录，失败可重试；不新增后台任务、不调用向量候选检索、不推断跨批语义关联。现有测试临时副本已完整复制 services、core 和 alembic，覆盖新增模块与迁移。

记忆的 `source_message_id_bound` 为独立整数上界，不随消息外键删除而置空；普通原卡与整理产物统一用它约束祖先记忆可见性。分支整理关联、来源保护和撤销依赖检查均按当前故事实际可见范围解析，不能仅按全局关联是否存在判断。

角色状态由 `services/conversation/role_state_service.py` 按会话基线与有效消息增量重放；纯形状校验在 `role_state_schema.py`。Prompt 注入当前状态，流式与非流式生成共用可选增量解析，回复和增量在同一事务保存。人工校正沿用会话锁并在 SQLite 写事务内校验版本；候选、删除和分支通过消息归属及起点快照保持隔离。详见[当前角色状态](ROLE_STATE.md)。

图谱由 `services/memory/graph_service.py` 追加实体与关系版本，`graph_evidence.py` 校验消息、记忆指纹和分叉边界。提纯使用原数组下标关联记忆依据；聊天装配传入当前用户消息边界，召回不接受无来源旧行。记忆整理收起的原卡仍可作为证据，语义替代与人工改写则使对应证据失效。详见[图谱与长期记忆的一致性](GRAPH_MEMORY_CONSISTENCY.md)。

`joint_retrieval.py` 编排向量种子、图谱扩展、SQLite 支持卡回查、整理摘要映射和共同预算；`memory_facts.py` 提供共用载荷、故事时间语义及自动卡来源校验。Prompt 接收统一事实卡，图谱不单独注入重复正文；ChromaDB 继续只作可重建索引。

## 后台任务

Outbox 任务保存在 `app.state.outbox_task` 中，由创建它的 lifespan 管理。关闭时取消并等待任务退出，不再靠应用入口修改 Worker 的全局开关。未完成的持久任务沿用 Outbox 原有租约与幂等重试机制。

后台流式对话在客户端断连后继续生成与落库；lifespan 关闭时调用对话任务清理入口。写库与失败清理延迟响应取消，等待正在运行的线程结束后再关闭数据库会话、释放会话锁，避免同一 Session 被保存和回滚并发访问。

## 兼容与验证

- HTTP 路由契约快照位于 `app-backend/tests/fixtures/http_routes.json`，新增接口需同步更新。
- 音频鉴权和当前恢复行为保持原样；缺失 `p2` 文件的限制仍见 [API 总表](../API_TABLE.md)。
- 测试入口和范围见 [测试指南](../app-backend/tests/README.md)，维护命令见 [工具说明](../app-backend/scripts/README.md)。
- 每次移动代码都同步修改导入、测试临时副本的复制范围和文档，运行 `python -m tests` 后再继续下一层调整。

进一步整理应优先检查基础设施客户端的导入期初始化、`core/config.py` 的配置职责，以及角色卡解析和 TTS 的领域归属。这些变更需要各自的行为测试，不通过单纯改目录一次性混入。
