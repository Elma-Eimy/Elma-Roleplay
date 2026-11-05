# 后端架构与职责

## 启动与请求链路

```text
main.py
  └─ application.factory.create_app()
       ├─ CORS、静态资源、鉴权依赖和路由装配
       └─ application.lifecycle.lifespan
            ├─ 启动：Alembic 升级 → 创建 Outbox、记忆重试与 CHARX 清理任务 → 启动提示
            └─ 关闭：等待记忆处理线程 → 取消 Outbox 与 CHARX 清理任务 → 清理后台对话 Worker

HTTP 请求 → routers/ → services/ → core/ 与基础设施客户端
维护命令 → scripts/ → core/ 与基础设施客户端
```

保持从 `app-backend/` 执行 `uvicorn main:app --reload`。应用工厂也可通过 `uvicorn application.factory:create_app --factory` 使用。

`create_app()` 只组装应用，不执行数据库迁移或启动 Worker。向量依赖通过 `services/infrastructure/clients.py` 的 `get_chroma_client()` 和 `get_embedding_function()` 首次使用时创建，分别加锁并在进程内复用；构造失败不缓存，下次使用可以重试。仅导入服务或创建应用不会构造这两项资源，删除向量集合也无需创建 Embedding 函数。

这不代表应用创建没有其他副作用：配置加载、数据库引擎和头像目录等仍沿用现有行为。ChromaDB 与 Embedding 构造错误在首次使用时暴露，而非路由导入时；Outbox 调用失败沿用已有持久重试机制。模型、地址与存储路径仍使用现有配置，不支持靠重复获取函数热切换已创建的资源。

生命周期内的 `run_migrations()` 通过 Alembic 配置属性关闭迁移环境的日志重配置，沿用 Uvicorn 或其他宿主已有的日志级别与处理器；独立命令行迁移仍加载 `alembic.ini`，但不禁用已存在的日志器。测试临时副本包含 `core/`、`alembic/` 和配置文件，启动迁移日志回归在独立进程中执行真实升级，避免污染其他测试的日志状态。

## 模块边界

群聊 M1-A 已建立 `Session.kind` 与 `Session.personas` 数据基础。单聊使用 slot 0，群聊预留 slot 1–3；`Session.persona` 只读兼容单聊，对群聊返回空。`services/conversation/session_access.py` 在旧入口读取或修改前检查类型，应用工厂统一将类型冲突转换为 HTTP 409。旧单聊列表在计数和分页前排除群聊；角色被群聊引用时拒绝删除。M1-B/C 已提供群聊创建、来源快照和删除服务及 HTTP 接口，M1-D 已接入最小页面，群聊生成尚未开放。

HTTP 接口通过 `application/session_routes.py` 声明访问策略：现有接口使用默认单聊的 `SessionAPIRouter`，群聊管理使用 `GroupSessionAPIRouter`。路由在 FastAPI 完成参数校验后、调用业务函数前，检查路径/查询参数和 Pydantic 请求模型中的 `session_id`、`parent_session_id`、`persona_id`、`message_id`；嵌套模型与模型列表同样检查，自由格式元数据不作为资源引用。新增同类接口自动获得所属策略的类型限制，漏用路由类型会在应用装配时失败；资源入口缺少 `db` 依赖时拒绝执行。鉴权、422 参数错误及原接口的资源不存在语义继续保留。

直接服务调用和后台重试仍通过 `get_single_session`、`get_single_message` 或 `get_single_persona` 加载资源；内部步骤复用已加载对象，跨事务重新加载。`api/test_session_access_architecture.py` 自动发现全部服务中同时声明 `db` 和上述资源参数的公开函数、类方法，使用群聊夹具验证拒绝访问且不改动数据，不维护入口名单。按显式人格隔离的共享算法使用 `@session_kind_agnostic("原因")` 声明例外；该标记不豁免 HTTP 校验，新增例外需要审查其成员选择与分支语义。自建数据库会话的回合维护、按任务 ID 调度的 Worker 继续由后台专项测试覆盖。群聊专用服务使用 `@group_session_operation` 声明类型，自动发现测试对其传入单聊资源验证反向隔离。新增资源标识命名或新的任务调度机制时，需要扩展发现规则和专项测试。

`services/conversation/group_session_service.py` 在来源锁与 SQLite 写事务内原子创建群聊及成员快照；快照来源 ID 不设动态外键，删除来源不影响已冻结事实。创建、删除和角色删除通过写事务串行化引用检查，群聊删除与本群资源的 Outbox 登记同进同退。继承快照当前只作持久交接，不进入单聊检索、任务或向量索引。

M2-A 的 `services/conversation/group_history_service.py` 管理内部轮次创建、完整内容与知情结果的原子追加、候选终态及个人历史查询，不调用模型或提供 HTTP 入口。`group_rounds`、`group_round_candidates`、`group_content_items`、`group_content_visibility` 通过组合外键约束同群归属；所选候选使用延迟校验外键解决循环引用，普通业务外键保持开启。新迁移只给旧 Session/Persona 增加目标唯一索引，不重建旧表；非空群聊轮次拒绝降级。

个人历史显式校验群聊、Persona 和当前未确认所选候选，独立 SQLite 读事务内筛选此前已确认的所选成功候选及当前 sequence 边界，按可见性过滤后再取最近 N 项。缺失知情行默认隐藏并报告内部告警；返回不可变 DTO，不附加全群原文、内部状态或隐藏项摘要。DTO 的内容 ID 和全局顺序仅供内部溯源，后续 Prompt 编译不能暴露由它们推断出的隐藏内容数量。读取不授予模型执行权；M2-B 必须在会话锁内校验候选版本后使用输入，并在落库时重新核验。

M2-A 的公开服务入口在接管事务前检查待提交 ORM 修改和底层 SQLite 活动事务，类型预读取禁止 autoflush。若调用方已修改、flush 或显式开启事务，则拒绝操作并保留其事务，不进入内部 rollback 清理；服务只负责自己取得的事务。普通只读预查询形成的 SQLAlchemy 逻辑事务仍可结束后重新取得快照。

M2-B 的 `group_context_service.py` 在同一读快照内取得个人历史和自身状态，复用既有角色卡 DSL、示例、世界书和参数准备，返回序列化的不可变调用快照。`prompt_compiler.build_group_messages` 共享单聊编译主体，但不改写真人用户原文，不为隐藏用户项补发 user 消息；其他成员正文使用有身份的 JSON user 消息，自身发言使用 assistant 格式。世界书扫描只接收同一份可见内容，PHI 与群聊输出契约后置。内部 ID/全局 sequence 不进入模型历史；仅自身历史附带自己的心情和好感变化，其他成员的内部状态不会进入输入。

世界书扫描与模型消息包装分别构造：扫描只用个人可见正文原文，模型历史仍使用 JSON 身份或 assistant XML。不能拿转义后的模型消息扫描，否则引号、标签等关键字会漏触发，身份字段或 status 标签也会误触发词条。

群聊状态从 M1 不可变起点及已确认所选候选、本轮当前候选中较早的自身增量重放，不受历史窗口截断影响。共同设定优先于来源初始场景，但作为可长达 20000 字的背景独立提供，不能塞入限长 300 字的 scene；后续自己的 scene 增量继续生效。群聊 state_update.characters 只允许自己的角色卡名称，不能修改其他 Persona；不覆盖起点、不进入单聊消息或记忆任务。

`group_generation_service.py` 要求 `core.locking.GroupRuntimeOwner` 对应同一 Engine 且仍有效，全程持有会话锁。外部模型与知情判定不持有 SQLite 事务，模型只调用一次；接收者回调只取得正文与作者 ID，不取得 reasoning 或内部状态。严格校验单个 reply/status 与可选状态增量，截断或无效输出失败；落库前重新检查运行权、候选版本和状态，正文、状态与知情集合原子提交。取消后等待已派发数据库线程完成再释放锁，可能已保存的前缀保留并标失败；迟到结果不改写已经推进或结束的版本。

取消优先于等待期间发生的普通数据库异常，线程结束后仍传播取消。另存失败状态的操作若也失败，只记录异常类型，不替换原始生成错误或取消，不输出 SQL 正文参数；无法持久化的 generating 候选由后续启动中断处理收敛。

M2-C 的只读轮次路由调用 `group_history_service.list_group_rounds`，面向故事操作者按整轮分页、各轮只取所选候选，包含失败前缀，不返回 reasoning、知情行或状态增量。该视图可包含操作者看到的全部正文，不能用作角色个人上下文；普通发送、确认、候选切换与恢复接口仍未开放。

M3-A 的 `group_director_service.py` 负责导演严格 JSON 协议和独立读快照。导演只读有效候选正文、完整知情结果、共同设定和成员 ID/名称，不读角色卡私密字段、来源聊天、私人认知或状态；角色继续使用 M2 个人输入。导演载荷按完整项应用字符预算，当前前缀及暂存待判正文不能静默截断。`scripts/group_chat_prototype/` 仅在独立源码副本与虚构临时库中回放，现已复用 M3-B 内部编排与任务登记，普通生成 API 仍关闭，持久导演审计已由 M3-C 接入。具体用法和未完成边界见[工具说明](../../app-backend/scripts/README.md)。

阶段编译将 stage 和待判内容一起计入预算，快照携带的内部本轮项数限定可省略范围，只移除较早的已确认内容，不暴露该边界元数据。隔离原型以最终候选终态的明确成功提交作为完成点：等待期间取消也返回成功结果和新 revision；最终写入失败则继续传播取消并按版本标失败。

M3-B 的 `group_round_service.py` 在整轮内持有 core.locking 的任务执行令牌，M2 单步入口作为兼容包装登记到同一运行权拥有者。令牌同时校验任务、Engine、会话、锁和登记对象身份，持权内部步骤不重新加锁。`group_call_snapshot.py` 在起始快照中冻结统一模型/思考选择、成员采样、输出上限和个人历史预算；模型与知情判断期间无数据库事务。专属客户端冻结连接并禁用 SDK 重试，单次/整轮超时与最多 `3K+1` 次调用由程序限制；默认结果只含阶段元数据，原型显式收集完整输入。

lifespan 通过 app.state.group_runtime_owner 提供内部运行权，关闭先停止接收新群聊，再取消并等待全部登记任务、持久化和后台 Worker。客户端关闭与数据库线程同样等待清理，重复取消不会提前释放文件锁。B 批未增加表或迁移；C 批在此基础上接入下述 v2 单元和审计，v1 保留为显式兼容路径。

M3-C 的 `group_unit_protocol.py` 严格校验用户连续完整码点范围、角色 1–8 个 speech/action/thought 单元和全成员知情覆盖。`group_unit_service.py` 保存同候选父项下的单元及权限；用户单元只保存原文范围，角色单元保存原始文本。个人查询先过滤单元，再按原顺序合并获准内容；v2 缺失记录按不可见处理，不回退父项全文，thought 即使权限异常也只允许作者读取。父项仍保存一次心情、好感和状态增量，完整自身权限缺失时不重放状态。世界书扫描复用同一份个人正文。

`group_audit_service.py` 只保存已接受的单元索引/原文范围、成员判定、调度动作、revision 链、模型和策略版本，不保存 Prompt、正文副本或 reasoning。初判与用户项、后判与发言项、结束决定与终态各自原子提交；选人决定先提交并推进 revision，再调用角色。正常终止保存 wait_user/no_visible_basis/step_limit，与 failed.error_code 分开；审计不进入角色输入或普通 rounds 响应。

整轮失败由 `group_round_service` 统一标记并取得该次实际提交的 revision，内部角色步骤不重复结束同一候选；独立单步入口仍负责自己的失败标记。发言保存后收到取消会把明确提交版本交回整轮，再按该版本清理。失败写入遇到版本竞争或不可写时保留最后接受的版本，不将外部推进误报为本次成果。

迁移 `b0d1e2f3a4b5` 在原 head 后追加 Candidate 协议/终止字段、单元/知情表和导演审计表。旧项回填一个单元，按 Python 码点映射原文并照抄既有权限，不重新判定；旧数据仍以 v1 权限为准。组合外键限制同候选和同群归属，删除级联与 Outbox 事务共同回滚；存在 v2 候选、终止原因或审计时拒绝有损降级。v2 最终 JSON 契约替换原 XML 输出指令，角色卡 DSL、PHI 和单聊协议保持原编译入口。

每次模型返回后同时检查整轮与单次绝对截止时间，适配器捕获取消后返回的迟到结果也按超时拒绝。隔离诊断读取失败只产生 diagnostic_error_code，不改变成功候选；报告将 input_collection 标为未通过。取消仍等待诊断线程结束并传播，原始异常正文和 SQL 参数不进入诊断错误码或日志。

`application/group_runtime.py` 将运行权绑定到 SQLite 文件旁的 `.runtime.lock`：Windows 使用 msvcrt 字节锁，其他支持的平台使用 flock。lifespan 先独占运行权，再迁移并将残留 generating 候选改为 failed/process_interrupted、递增 revision，随后启动 Worker；关闭并等待任务结束后才释放运行权。第二个应用进程会在迁移和中断处理前失败，避免误判其他 Worker 的正在执行候选。锁文件保留，锁随句柄或进程退出释放；不自动恢复或再次调用模型。

关闭清理通过独立任务统一取消并等待后台 Worker，再清理聊天流；单个 Worker 已异常退出时也继续处理其余任务。lifespan 的重复取消不会传入该清理任务，清理完成后才传播取消或 Worker 错误并释放运行权，避免后台仍在写库时允许新进程接管。

列表筛选与角色删除保护仍是各自的业务规则。群聊路由仅允许 group 目标；创建请求中的 `origin.session_id` 映射为内部 `source_session_id`，始终按 single 来源检查。来源与目标不会共用一个模糊的类型豁免。不同策略不能重复包装同一业务入口；后续群聊子资源也沿用明确的策略及归属校验。

Alembic 在线迁移在事务外暂停当前连接的外键执行，随后用 `BEGIN IMMEDIATE` 将表重建与版本号更新纳入同一事务，提交前执行 `foreign_key_check`，失败整体回滚，退出时恢复原外键设置。这样重建 Persona 或 Session 表时不会触发引用表的级联删除和置空。普通业务连接仍启用外键；含群聊数据时拒绝降级到 M1-A 之前的结构。

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

## 后台任务

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
