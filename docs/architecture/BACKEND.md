# 后端架构与职责

## 启动与请求链路

```text
main.py
  └─ application.factory.create_app()
       ├─ CORS、静态资源、鉴权依赖和路由装配
       └─ application.lifecycle.lifespan
            ├─ 启动：取得数据库运行权 → Alembic 升级 → 收敛中断群聊 → 启动 Outbox、单聊/群聊记忆与 CHARX 清理任务
            └─ 关闭：停止接受群聊 → 等待执行与后台任务清理 → 清理聊天流 → 释放数据库运行权

HTTP 请求 → routers/ → services/ → core/ 与基础设施客户端
维护命令 → scripts/ → core/ 与基础设施客户端
```

保持从 `app-backend/` 执行 `uvicorn main:app --reload`。应用工厂也可通过 `uvicorn application.factory:create_app --factory` 使用。

`create_app()` 只组装应用，不执行数据库迁移或启动 Worker。向量依赖通过 `services/infrastructure/clients.py` 的 `get_chroma_client()` 和 `get_embedding_function()` 首次使用时创建，分别加锁并在进程内复用；构造失败不缓存，下次使用可以重试。仅导入服务或创建应用不会构造这两项资源，删除向量集合也无需创建 Embedding 函数。

这不代表应用创建没有其他副作用：配置加载、数据库引擎和头像目录等仍沿用现有行为。ChromaDB 与 Embedding 构造错误在首次使用时暴露，而非路由导入时；Outbox 调用失败沿用已有持久重试机制。模型、地址与存储路径仍使用现有配置，不支持靠重复获取函数热切换已创建的资源。

生命周期内的 `run_migrations()` 通过 Alembic 配置属性关闭迁移环境的日志重配置，沿用 Uvicorn 或其他宿主已有的日志级别与处理器；独立命令行迁移仍加载 `alembic.ini`，但不禁用已存在的日志器。测试临时副本包含 `core/`、`alembic/` 和配置文件，启动迁移日志回归在独立进程中执行真实升级，避免污染其他测试的日志状态。

## 模块边界

群聊的数据、个人上下文、导演、后台恢复与成员记忆机制见 [群聊架构](GROUP_CHAT.md)。功能范围查 [群聊说明](../features/GROUP_CHAT.md)，HTTP 契约查 [群聊接口](../api/GROUP_SESSIONS.md)。

| 位置 | 负责 | 不应放入 |
| --- | --- | --- |
| `main.py` | 暴露 ASGI 的 `app` | 接口处理、数据查询、后台任务管理 |
| `application/` | 应用工厂、生命周期、启动提示 | 领域业务规则 |
| `routers/` | 路径、输入校验、鉴权依赖、HTTP 响应与异常转换 | 复杂查询、文件恢复和对话编排 |
| `services/conversation/` | 会话、消息、Prompt、模型执行和对话回合 | FastAPI 应用创建 |
| `services/memory/` | 记忆提纯、版本、继承、检索、图谱和管理查询 | HTTP 路由装配 |
| `services/lorebook/` | 世界书解析、触发和注入 | 服务器启动逻辑 |
| `services/media/` | 角色卡图片导入、立绘资源与选择、音频缓存文件查找与恢复 | HTTP 状态码与 `FileResponse` |
| `services/infrastructure/` | LLM/向量客户端、Outbox 和模型日志 | 页面展示逻辑 |
| `core/` | 配置、ORM、数据库会话、迁移函数、锁和基础工具 | 路由注册与后台任务启动 |
| `schemas.py` | 当前 Pydantic 请求模型 | ORM 表定义或数据库操作 |
| `scripts/` | 显式执行的查询和重置工具 | 自动启动的业务流程 |
| `tests/` | 自动回归和独立手动场景 | 生产业务实现 |

`character_service.py`、`parse.py` 和 `tts_service.py` 暂保留在 `services/` 根目录，分别承担角色、角色卡解析和 TTS 功能。后续可按领域继续组织，迁移时应同时更新调用方，避免保留多份实现。

`services/conversation/chat_engine.py` 的 `_prepare_generation_kwargs()` 为流式与非流式生成统一准备参数，按请求、角色卡和全局默认值解析采样与思考设置，再交给模型能力适配。两个生成入口分别保留原有调用、响应解析及错误处理；上下文装配与回合持久化不进入参数准备函数。

Prompt 模块集中在 `services/conversation/prompting/`。调用方从对应模块导入，包内使用相对导入；`__init__.py` 不统一加载编译器或业务服务。`compiler.py` 保留编译入口、已有导出和群聊适配，`build_chat_messages()` 只编排编译步骤。内部依赖按职责拆分：

| 模块 | 职责 |
| --- | --- |
| `prompting/templates.py` | 角色卡宏、占位符、静态指令与后置输出协议 |
| `prompting/examples.py` | 示例分块、发言者解析与无法结构化时的回退 |
| `prompting/lorebook.py` | 世界书内容编译、角色深度提示词和深度插入算法 |
| `prompting/context.py` | 世界书触发输入、记忆时间标签与当前回合动态背景 |
| `prompting/layout.py` | 静态及示例前缀、历史格式转换、动态背景定位 |
| `prompting/token_estimator.py` | 最终消息的启发式 Token 范围估算与分区统计 |

模板和示例不依赖装配入口；消息排列不计算角色状态或调用记忆检索。动态背景先编译成有序文本块，再交给排列模块插入；业务数据库查询仍由上下文装配层及其领域服务完成。静态消息合并、示例边界、当前输入定位及最终输出协议保持原规则。单聊和群聊入口仍共用编译流程，群聊输入适配保留在原入口。

`context_compression.py` 负责单聊摘要版本、来源校验、原文覆盖及分支冻结。聊天路由允许装配层按需调用压缩模型，预览只读；模型调用期间提交并结束读取事务，返回后用短写事务复核来源及版本。摘要由 `prompting/context.py` 编译，经入口固定放在最近原文之前，不改变深度插入算法或长期记忆查询。持久化、失败保留及旧分支升级边界见[会话上下文压缩](../features/CONTEXT_COMPRESSION.md)。

`conversation/test_prompt_compilation_snapshot.py` 使用拆分前保存的完整消息快照，逐项比较角色、内容和顺序，覆盖单聊、分支示例、动态状态、世界书及两种群聊协议。固定虚构输入不调用真实模型；测试临时副本按现有规则复制整个 `services/` 和 `tests/`，包含所有新增模块与快照。

`application/charx_upload.py` 在读取 CHARX 请求体前完成鉴权，限制流式请求总字节与并发上传，再交给仅允许一个文件的 multipart 解析。`services/media/charx_plan.py` 明确 CCv3 字段映射与兼容性报告；`charx_import.py` 负责有界 ZIP 读取、短期预览、素材去重与确认保存。解压和像素解码在生命周期锁外运行，同一 ZIP 条目的失败也缓存；临时目录不公开。`application.lifecycle` 管理每 60 秒回收过期预览的任务。状态接口从 SQLite 幂等回执恢复已提交结果，不依赖临时文件；取消/过期仅保留短期状态标记。`character_portraits.content_sha256` 支持跨上传去重，旧资源按需填充，资源共享仍沿用 Outbox 引用检查。保持单进程部署，不引入额外任务队列。

`schemas.py` 当前体量较小，仍集中管理；`core/models.py` 的 ORM 关系和迁移链保持原样。数据库、头像、音频、配置和虚拟环境位置不因代码目录整理而移动。

CHARX 确认区分新建、追加素材和更新已有角色；设定合并、独立世界书同步、默认开场交换与素材写入、回执在同一事务完成。已有角色名称保留，世界书只有显式开启同步时替换。GIF/APNG/WebP 保留原文件，逐帧校验并累计解码预算，单图最多 300 帧；首帧缩略图不代替原动画。预览位于系统临时目录，确认后的所选资源进入 `app.upload_avatar_dir`；目录规则和客户端能力边界见[角色卡说明](../features/CHARACTER_CARDS.md#charx-首版)。

记忆整理由 `services/memory/memory_consolidation_service.py` 编排，`memory_visibility.py` 解析消息分叉边界和故事整理快照。整理记录、来源关联与 Persona 整理范围分别持久化；新分支复制当时的整理范围，父故事后续撤销不会回写子故事。原卡保留，列表/统计/检索共享有效视图，写入沿用 Outbox。详情见 [记忆 API](../api/MEMORY_API.md)。

手动增量扫描由 `memory_consolidation_scan.py` 维护原卡版本指纹；`memory_consolidation_scans` 通过 Alembic 新增，扫描进度与整理应用状态分离。先按 SQLite 有效本地原卡视图逐页比对版本，再将最多 100 张未检查/变更卡送给模型；外部调用结束后在短写事务内重新核对当前版本，并与预览原子保存。仅保存成功且版本未变的卡推进检查记录，失败可重试；不新增后台任务、不调用向量候选检索、不推断跨批语义关联。现有测试临时副本已完整复制 services、core 和 alembic，覆盖新增模块与迁移。

送检时按记忆类型隔离输入，每次调用只允许引用该次来源；非事件类型仅做去重，各类型串行共用 12 组预算与诊断关联 ID，统一编号后仍由同一事务保存。整个模型调用阶段不持有数据库事务，任一类型失败都不落地此前的部分建议。质量验收按类型回放完整建议，并保留各次响应及 Prompt 哈希。

记忆的 `source_message_id_bound` 为独立整数上界，不随消息外键删除而置空；普通原卡与整理产物统一用它约束祖先记忆可见性。分支整理关联、来源保护和撤销依赖检查均按当前故事实际可见范围解析，不能仅按全局关联是否存在判断。

角色状态由 `services/conversation/role_state_service.py` 按会话基线与有效消息增量重放；纯形状校验在 `role_state_schema.py`。Prompt 注入当前状态，流式与非流式生成共用可选增量解析，回复和增量在同一事务保存。人工校正沿用会话锁并在 SQLite 写事务内校验版本；候选、删除和分支通过消息归属及起点快照保持隔离。详见[当前角色状态](../features/ROLE_STATE.md)。

图谱由 `services/memory/graph_service.py` 追加实体与关系版本，`graph_evidence.py` 校验消息、记忆指纹和分叉边界。提纯使用原数组下标关联记忆依据；聊天装配传入当前用户消息边界，召回不接受无来源旧行。记忆整理收起的原卡仍可作为证据，语义替代与人工改写则使对应证据失效。详见[图谱与长期记忆的一致性](../features/GRAPH_MEMORY_CONSISTENCY.md)。

`joint_retrieval.py` 编排向量种子、图谱扩展、SQLite 支持卡回查、整理摘要映射和共同预算；`memory_facts.py` 提供共用载荷、故事时间语义及自动卡来源校验。Prompt 接收统一事实卡，图谱不单独注入重复正文；ChromaDB 继续只作可重建索引。

群聊候选转换由 `services/conversation/group_candidate_state.py` 集中维护；任务与持久目标的执行校验在 `group_execution_scope.py`，事务仍由历史、检查点和操作接受服务持有。状态规则与数据库提交分开，具体边界见[群聊架构](GROUP_CHAT.md#候选生命周期与执行校验)。

## 会话类型隔离与迁移

新共同群聊的已接受调度在 `group_dispatches` 独立保存，审计只提供镜像记录；`group_dispatch_service.py` 管理业务调度，`group_legacy_protocol.py` 处理旧候选的审计兼容。版本标记、迁移和恢复边界见[群聊业务调度](GROUP_CHAT.md#业务调度与旧协议兼容)。

HTTP 接口通过 `application/session_routes.py` 声明访问策略：现有接口使用默认单聊的 `SessionAPIRouter`，群聊管理使用 `GroupSessionAPIRouter`。路由在 FastAPI 完成参数校验后、调用业务函数前，检查路径/查询参数和 Pydantic 请求模型中的 `session_id`、`parent_session_id`、`persona_id`、`message_id`；嵌套模型与模型列表同样检查，自由格式元数据不作为资源引用。新增同类接口自动获得所属策略的类型限制，漏用路由类型会在应用装配时失败；资源入口缺少 `db` 依赖时拒绝执行。鉴权、422 参数错误及原接口的资源不存在语义继续保留。

直接服务调用和后台重试仍通过 `get_single_session`、`get_single_message` 或 `get_single_persona` 加载资源；内部步骤复用已加载对象，跨事务重新加载。`api/test_session_access_architecture.py` 自动发现全部服务中同时声明 `db` 和上述资源参数的公开函数、类方法，使用群聊夹具验证拒绝访问且不改动数据，不维护入口名单。按显式人格隔离的共享算法使用 `@session_kind_agnostic("原因")` 声明例外；该标记不豁免 HTTP 校验，新增例外需要审查其成员选择与分支语义。自建数据库会话的回合维护、按任务 ID 调度的 Worker 继续由后台专项测试覆盖。群聊专用服务使用 `@group_session_operation` 声明类型，自动发现测试对其传入单聊资源验证反向隔离。新增资源标识命名或新的任务调度机制时，需要扩展发现规则和专项测试。

列表筛选与角色删除保护仍是各自的业务规则。群聊路由仅允许 group 目标；创建请求中的 `origin.session_id` 映射为内部 `source_session_id`，始终按 single 来源检查。来源与目标不会共用一个模糊的类型豁免。不同策略不能重复包装同一业务入口；后续群聊子资源也沿用明确的策略及归属校验。

Alembic 在线迁移在事务外暂停当前连接的外键执行，随后用 `BEGIN IMMEDIATE` 将表重建与版本号更新纳入同一事务，提交前执行 `foreign_key_check`，失败整体回滚，退出时恢复原外键设置。这样重建 Persona 或 Session 表时不会触发引用表的级联删除和置空。普通业务连接仍启用外键；含群聊数据时拒绝降级到 M1-A 之前的结构。

## 后台任务

群聊运行权、提纯 Worker 与关闭顺序见 [群聊生命周期](GROUP_CHAT.md#进程生命周期与隔离预览)。应用关闭等待清理完成后才释放数据库运行权。

进行中事件由 `memory_event_buffer.py` 纯内存规划并持久化到 `memory_event_buffers`。`memory_extraction_jobs.py` 先将候选与接收进度原子保存，再按依赖组件处理；所有外部调用位于写事务之外，提交时核对来源、旧卡、缓冲版本和租约。单独的 `memory_retry_worker.py` 退避重试，生命周期关闭会等待其线程结束。聊天装配向纯 Prompt 编译器传入有效事件和待处理候选；事件与图谱辅助来源分别失效。迁移和测试副本沿用现有复制范围，详见[进行中事件](../features/MEMORY_EVENTS.md)。

事件行同时承担持久身份，状态区分待写、阶段已保存和结束。容量检查保存追加阶段，`MemoryChunk.event_id` 关联阶段卡；跨批只追加新片段，已发布阶段不由自动查重替代。来源与分叉可见性继续逐卡校验，身份关联不扩大检索边界。固定虚构对话回放检查已提取事实线索的跨批保留，真实模型的提取质量需另行验收。

Outbox 任务保存在 `app.state.outbox_task` 中，由创建它的 lifespan 管理。关闭时取消并等待任务退出，不再靠应用入口修改 Worker 的全局开关。未完成的持久任务沿用 Outbox 原有租约与幂等重试机制。

后台流式对话在客户端断连后继续生成与落库；lifespan 关闭时调用对话任务清理入口。写库与失败清理延迟响应取消，等待正在运行的线程结束后再关闭数据库会话、释放会话锁，避免同一 Session 被保存和回滚并发访问。

## 兼容与验证

- HTTP 路由契约快照位于 `app-backend/tests/fixtures/http_routes.json`，新增接口需同步更新。
- API 文档回归同时检查总表路由覆盖和所有 JSON 请求接口的标记样本；隔离入口只额外复制总表和固定领域文档到 `project_docs/`，不复制本地资料。范围见 [API 维护与校验](../api/README.md)。
- 音频鉴权和当前恢复行为保持原样；缺失 `p2` 文件的限制仍见 [API 总表](../../API_TABLE.md)。
- 测试入口和范围见 [测试指南](../../app-backend/tests/README.md)，维护命令见 [工具说明](../../app-backend/scripts/README.md)。
- 每次移动代码都同步修改导入、测试临时副本的复制范围和文档，运行 `python -m tests` 后再继续下一层调整。

后续可继续检查 `core/config.py` 的配置职责、数据库引擎的初始化，以及角色卡解析和 TTS 的领域归属。这些变更需要各自的行为测试，不通过单纯改目录一次性混入。
