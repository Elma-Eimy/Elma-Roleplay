# 后端架构与职责

## 启动与请求链路

```text
main.py
  └─ application.factory.create_app()
       ├─ CORS、静态资源、鉴权依赖和路由装配
       └─ application.lifecycle.lifespan
            ├─ 启动：取得数据库运行权 → Alembic 升级 → 收敛中断群聊 → 启动 Outbox、单聊/群聊记忆与 CHARX 清理任务
            └─ 关闭：停止接受群聊与单聊维护 → 等待执行与后台任务清理 → 清理聊天流及维护线程 → 释放数据库运行权

HTTP 请求 → routers/ → services/ → core/ 与基础设施客户端
维护命令 → scripts/ → core/ 与基础设施客户端
```

保持从 `app-backend/` 执行 `uvicorn main:app --reload`。应用工厂也可通过 `uvicorn application.factory:create_app --factory` 使用。

`create_app()` 只组装应用，不执行数据库迁移或启动 Worker。向量依赖通过 `services/infrastructure/clients.py` 的 `get_chroma_client()` 和 `get_embedding_function()` 首次使用时创建，分别加锁并在进程内复用；构造失败不缓存，下次使用可以重试。仅导入服务或创建应用不会构造这两项资源，删除向量集合也无需创建 Embedding 函数。

这不代表应用创建没有其他副作用：配置加载、数据库引擎和头像目录等仍沿用现有行为。ChromaDB 与 Embedding 构造错误在首次使用时暴露，而非路由导入时；Outbox 调用失败沿用已有持久重试机制。模型、地址与存储路径仍使用现有配置，不支持靠重复获取函数热切换已创建的资源。

生命周期内的 `run_migrations()` 通过 Alembic 配置属性关闭迁移环境的日志重配置，沿用 Uvicorn 或其他宿主已有的日志级别与处理器；独立命令行迁移仍加载 `alembic.ini`，但不禁用已存在的日志器。测试临时副本包含 `core/`、`alembic/` 和配置文件，启动迁移日志回归在独立进程中执行真实升级，避免污染其他测试的日志状态。

## 模块边界

`core/config.py` 负责旧配置迁移、类型绑定、配置快照及串行原子保存。`core/model_settings.py` 是不读取全局配置的模型能力、选择与参数规则；基础设施层保留既有调用入口并向规则传入快照。模型和思考模式独立，各辅助任务分别解析；旧双模型槽位只在迁移和旧请求兼容时使用。保存失败不发布新状态，非法 YAML 不静默回退。详见[模型设置](../features/MODEL_SELECTION.md)。

群聊的数据、个人上下文、导演、后台恢复与成员记忆机制见 [群聊架构](GROUP_CHAT.md)。功能范围查 [群聊说明](../features/GROUP_CHAT.md)，HTTP 契约查 [群聊接口](../api/GROUP_SESSIONS.md)。

| 位置 | 负责 | 不应放入 |
| --- | --- | --- |
| `main.py` | 暴露 ASGI 的 `app` | 接口处理、数据查询、后台任务管理 |
| `application/` | 应用工厂、生命周期、启动提示 | 领域业务规则 |
| `routers/` | 路径、输入校验、鉴权依赖、HTTP 响应与异常转换 | 复杂查询、文件恢复和对话编排 |
| `services/conversation/` | 会话、消息、Prompt、模型执行和对话回合 | FastAPI 应用创建 |
| `services/conversation/group/` | 群聊会话、候选、导演、个人上下文与后台执行 | 成员记忆实现、媒体存储和应用生命周期 |
| `services/memory/` | 记忆提纯、版本、继承、检索、图谱和管理查询 | HTTP 路由装配 |
| `services/lorebook/` | 世界书解析、触发和注入 | 服务器启动逻辑 |
| `services/media/` | 角色卡图片导入、立绘资源与选择、音频缓存文件查找与恢复 | HTTP 状态码与 `FileResponse` |
| `services/infrastructure/` | LLM/向量客户端、Outbox 和模型日志 | 页面展示逻辑 |
| `core/` | 配置、ORM、数据库会话、迁移函数、锁和基础工具 | 路由注册与后台任务启动 |
| `schemas.py` | 当前 Pydantic 请求模型 | ORM 表定义或数据库操作 |
| `scripts/` | 显式执行的查询和重置工具 | 自动启动的业务流程 |
| `tests/` | 自动回归和独立手动场景 | 生产业务实现 |

群聊内部的归属校验、个人历史、操作者状态和前缀校验分别由 `group/guards.py`、`history_projection.py`、`state_projection.py` 和 `prefix_validation.py` 提供；历史写入、检查点与操作者查询沿同一方向复用，不相互读取私有校验。具体依赖和事务归属见 [群聊模块边界](GROUP_CHAT.md#代码组织与维护入口)。

`services/media/character_card_parser.py` 负责 JSON/PNG 角色卡读取、元数据写回和字段规范化，保留角色卡 Prompt DSL。`services/conversation/reply_parser.py` 负责单聊与群聊回复的 XML 容错、状态增量和流式正文前缀解析。两个解析模块可独立导入，不相互依赖，也不通过兼容入口加载对方；`services/parse.py` 只重导出原函数、正则与旧别名。生产服务、聊天路由和角色卡工具直接导入对应领域实现，旧导入仍指向同一函数对象。

`services/conversation/session_query_service.py` 统一单聊最近会话、角色会话列表、详情、当前故事历史和候选批量读取。`session_service.py` 保留创建、删除、分支与回复保存，并兼容导出原有查询函数；路由和记忆故事导航直接依赖查询模块。查询沿用调用方 Session，不自行提交、回滚或重新取得事务；详情缺失由服务返回空值，HTTP 404 仍由路由转换。列表继续在统计与分页前排除群聊，历史和候选只读取当前故事，不合并祖先原文。

`services/media/tts_text.py` 的 `TTSTextProcessor` 维护无 I/O 的台词规则、提示词构造、模型结果校验、截断和安全回退，可独立导入并执行，不加载配置、HTTP、模型或数据库模块。`TTSService` 继承该策略，保留原方法、阈值属性与实例覆盖方式；模型选择和同步/异步预处理调用、诊断装饰器、HTTP 客户端、缓存及消息绑定仍由 `services/tts_service.py` 管理。文本方法继续通过 `self` 调用，不创建另一份策略实例。

`services/infrastructure/tts_provider.py` 负责语音 URL/头/请求体构造、单次 POST 和直接音频或 Base64 响应解码。配置值和客户端由调用方显式传入，适配器不创建或关闭客户端、不读写缓存，也不打开数据库或提交事务。同步和异步路径分别保留原异常契约与日志字段；日志使用调用方传入的原服务 logger，并沿用外层任务编号。

异步客户端仍在原 `TTSService` 的上下文中持有，完成解码、写文件和消息提交后才关闭；同步路径继续复用 `_get_client()`，适配器不回收借用的客户端。取消不转换为普通请求失败，不重发 POST，退出异步客户端后保留原取消；缓存写入、绑定和清理只在请求与解码成功后继续。

本次不调整文本规则或提示词，预处理版本仍为 `2`，已存在的普通文本和消息绑定 p2 缓存继续命中；日志名称和任务编号包装保持原样。`character_service.py` 暂保留在 `services/` 根目录，会话剩余写入职责与 TTS 缓存、消息绑定边界按具体调用关系继续评估。

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

`conversation/prompting/test_prompt_compilation_snapshot.py` 使用拆分前保存的完整消息快照，逐项比较角色、内容和顺序，覆盖单聊、分支示例、动态状态、世界书及两种群聊协议。固定虚构输入不调用真实模型；测试临时副本按现有规则复制整个 `services/` 和 `tests/`，包含所有新增模块与快照。

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

群聊候选转换由 `services/conversation/group/candidate_state.py` 集中维护；任务与持久目标的执行校验在 `group/execution_scope.py`，事务仍由历史、检查点和操作接受服务持有。状态规则与数据库提交分开，具体边界见[群聊架构](GROUP_CHAT.md#候选生命周期与执行校验)。

## 会话类型隔离与迁移

新共同群聊的已接受调度在 `group_dispatches` 独立保存，审计只提供镜像记录；`group/dispatch_service.py` 管理业务调度，`group/legacy_protocol.py` 处理旧候选的审计兼容。版本标记、迁移和恢复边界见[群聊业务调度](GROUP_CHAT.md#业务调度与旧协议兼容)。

HTTP 接口通过 `application/session_routes.py` 声明访问策略：现有接口使用默认单聊的 `SessionAPIRouter`，群聊管理使用 `GroupSessionAPIRouter`。路由在 FastAPI 完成参数校验后、调用业务函数前，检查路径/查询参数和 Pydantic 请求模型中的 `session_id`、`parent_session_id`、`persona_id`、`message_id`；嵌套模型与模型列表同样检查，自由格式元数据不作为资源引用。新增同类接口自动获得所属策略的类型限制，漏用路由类型会在应用装配时失败；资源入口缺少 `db` 依赖时拒绝执行。鉴权、422 参数错误及原接口的资源不存在语义继续保留。

直接服务调用和后台重试仍通过 `get_single_session`、`get_single_message` 或 `get_single_persona` 加载资源；内部步骤复用已加载对象，跨事务重新加载。`api/test_session_access_architecture.py` 自动发现全部服务中同时声明 `db` 和上述资源参数的公开函数、类方法，使用群聊夹具验证拒绝访问且不改动数据，不维护入口名单。按显式人格隔离的共享算法使用 `@session_kind_agnostic("原因")` 声明例外；该标记不豁免 HTTP 校验，新增例外需要审查其成员选择与分支语义。自建数据库会话的回合维护、按任务 ID 调度的 Worker 继续由后台专项测试覆盖。群聊专用服务使用 `@group_session_operation` 声明类型，自动发现测试对其传入单聊资源验证反向隔离。新增资源标识命名或新的任务调度机制时，需要扩展发现规则和专项测试。

列表筛选与角色删除保护仍是各自的业务规则。群聊路由仅允许 group 目标；创建请求中的 `origin.session_id` 映射为内部 `source_session_id`，始终按 single 来源检查。来源与目标不会共用一个模糊的类型豁免。不同策略不能重复包装同一业务入口；后续群聊子资源也沿用明确的策略及归属校验。

Alembic 在线迁移在事务外暂停当前连接的外键执行，随后用 `BEGIN IMMEDIATE` 将表重建与版本号更新纳入同一事务，提交前执行 `foreign_key_check`，失败整体回滚，退出时恢复原外键设置。这样重建 Persona 或 Session 表时不会触发引用表的级联删除和置空。普通业务连接仍启用外键；含群聊数据时拒绝降级到 M1-A 之前的结构。

## 后台任务

群聊运行权、提纯 Worker 与关闭顺序见 [群聊生命周期](GROUP_CHAT.md#进程生命周期与隔离预览)。应用关闭等待清理完成后才释放数据库运行权。

进行中事件由 `memory_event_buffer.py` 纯内存规划并持久化到 `memory_event_buffers`。`memory_extraction_jobs.py` 先将候选与接收进度原子保存，再按依赖组件处理；所有外部调用位于写事务之外，提交时核对来源、旧卡、缓冲版本和租约。单独的 `memory_retry_worker.py` 退避重试，生命周期关闭会等待其线程结束。聊天装配向纯 Prompt 编译器传入有效事件和待处理候选；事件与图谱辅助来源分别失效。迁移和测试副本沿用现有复制范围，详见[进行中事件](../features/MEMORY_EVENTS.md)。

事件行同时承担持久身份，状态区分待写、阶段已保存和结束。容量检查保存追加阶段，`MemoryChunk.event_id` 关联阶段卡；跨批只追加新片段，已发布阶段不由自动查重替代。来源与分叉可见性继续逐卡校验，身份关联不扩大检索边界。固定虚构对话回放检查已提取事实线索的跨批保留，真实模型的提取质量需另行验收。

Outbox 任务保存在 `app.state.outbox_task` 中，由创建它的 lifespan 管理。每轮查询、领取、外部执行、成功删除或失败退避及 Session 关闭均在同一个工作线程执行，SQLite 锁等待不占用事件循环。关闭或取消时通知线程停止领取后续任务，已开始领取的当前任务仍完成执行与结果记录，再关闭 Session；重复取消不提前结束等待。未完成的持久任务沿用原有租约与幂等重试机制，不新增队列或并行消费。

后台流式对话在客户端断连后继续生成与落库；lifespan 关闭时调用对话任务清理入口。写库与失败清理延迟响应取消，等待正在运行的线程结束后再关闭数据库会话、释放会话锁，避免同一 Session 被保存和回滚并发访问。

`application/chat_maintenance.py` 为每次 lifespan 创建单聊维护任务登记表，流式与非流式回复保存成功后统一提交维护任务。关闭开始即拒绝新增，聊天流清理后取消并等待已登记维护；取消只作用于外层任务，正在执行的工作线程完成记忆检查、认知调用及数据库会话关闭后，等待才结束。重复取消不会提前释放运行权；维护异常按故事与人格编号记录，不改变已保存回复。维护任务不持久排队，关闭后未受理的检查由后续回合或手动入口触发。

`services/memory/cognition_service.py` 在显式读取事务中冻结旧认知、进度、人格与分支归属及新增 active 消息的正文、角色、父消息和顺序，提交后才调用模型。返回时先以 `BEGIN IMMEDIATE` 取得 SQLite 写权，再重新加载并复核版本及冻结消息区间；编辑、删除、候选切换、分支边界变化或另一更新已发布时，丢弃结果且不推进进度。冻结区间之后新增的消息留待下次处理，父故事未来消息和平行故事不进入输入。这里的版本是旧状态与来源值的比对，不新增数据库版本列，也不追溯重建此前已经发布的认知。

## 日志与诊断

聊天入口、引擎及回合维护、Outbox 和 TTS 使用 Python logging 记录事件、任务编号、资源编号、HTTP 状态码与错误类型。`services/infrastructure/logging_context.py` 用 ContextVar 关联同一次聊天的引擎、流式 Worker 及维护线程；TTS 的预处理沿用外层任务编号，Outbox 按 `outbox-{job_id}` 关联执行和重试。业务日志不序列化请求、音频台词、供应商响应正文或异常正文，缓存细节使用 DEBUG，正常阶段使用 INFO，失败和退避使用 WARNING/ERROR。原有宿主日志器的级别、处理器及输出位置保持不变，部署环境负责普通日志的收集与轮转；需要 INFO 诊断时需为对应模块配置级别和处理器。本轮未将其他领域的所有 `print()` 批量替换。

`services/infrastructure/llm_logger.py` 保留同步、异步流与旧原始响应入口，详细模型日志由 YAML 的 `logging` 节配置，默认关闭。单聊流式及非流式生成可写入请求、正文与思考的有界摘录，其他辅助模型调用不会因此自动记录全文。关闭时不检查消息与 chunk 的诊断字段、不积累输出缓冲；开启后按单次字节预算截断，再写入 JSONL。配置中的聊天、Embedding、MIMO 和访问密钥会被替换，跨 chunk 的密钥也在拼接后处理；任意未配置的秘密或个人内容仍可能出现在摘录中，应按私有诊断资料保存。

默认写入后端目录下的 `logs/llm_debug.log`，每份最多 1 MiB，另保留 3 份编号备份。文件轮转按 UTF-8 实际字节计算，单条记录也受文件上限约束，并发写入在进程内串行；超大输出不无限累积。异步聊天及异步流将日志完成阶段的序列化、文件锁等待、打开、写入和轮转放入工作线程，慢写盘不占用事件循环。取消及重复取消会等待正在运行的日志操作结束后再传播，生命周期在线程中关闭句柄；当前回合或关闭仍会等待其在途日志操作完成。日志打开、写入、轮转与宿主处理器故障仅记录错误类型，不改变 chunk、模型异常或回复落库结果。新增日志器不配置 root/Uvicorn，也不在导入或创建应用时创建日志文件；本方案沿用单进程部署约束。

日志配置修改后需重启，不加入设置 HTTP 接口。`llm_debug_max_bytes` 范围为 4096–104857600，`llm_debug_backup_count` 为 1–20，`llm_debug_excerpt_bytes` 为 128–65536；非法值在配置候选保存前拒绝。文件预算较小时会进一步压缩摘录长度。旧后端目录中的 `llm_debug.log` 不再追加，也不自动删除或迁移；自定义路径已有的旧文件及修改保留策略前留下的额外备份需单独归档。

## 兼容与验证

- HTTP 路由契约快照位于 `app-backend/tests/fixtures/http_routes.json`，新增接口需同步更新。
- API 文档回归同时检查总表路由覆盖和所有 JSON 请求接口的标记样本；隔离入口只额外复制总表和固定领域文档到 `project_docs/`，不复制本地资料。范围见 [API 维护与校验](../api/README.md)。
- 音频鉴权和当前恢复行为保持原样；缺失 `p2` 文件的限制仍见 [API 总表](../../API_TABLE.md)。
- 测试入口和范围见 [测试指南](../../app-backend/tests/README.md)，维护命令见 [工具说明](../../app-backend/scripts/README.md)。记忆共用数据与模型替身位于 `tests/support/memory/`，群聊迁移旧库与快照位于 `tests/support/migrations/`；夹具不继承 `TestCase`，不反向导入测试模块，隔离副本沿用完整复制 `tests/` 的范围。
- 每次移动代码都同步修改导入、测试临时副本的复制范围和文档，运行 `python -m tests` 后再继续下一层调整。

后续可继续检查 `core/config.py` 的配置职责、数据库引擎的初始化，以及 TTS 缓存和消息绑定的边界。这些变更需要各自的行为测试，不通过单纯改目录一次性混入。
