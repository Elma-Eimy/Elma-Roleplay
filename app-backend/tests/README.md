# 后端测试

自动回归按职责分组，沿用标准库 `unittest`。使用当前后端虚拟环境，在 `app-backend/` 目录执行命令。

## 自动回归

`conversation/group/test_group_dispatch.py` 验证新候选在审计清空后仍能预览、续接和进入下一轮，结束检查点零调用恢复、业务调度损坏拒绝、旧候选兼容，以及审计写入失败时调度和回复原子回滚。`infrastructure/test_group_dispatch_migration.py` 验证旧数据不回填、组合归属约束、升级失败回滚及有损降级保护；均使用临时库和模型替身。

`conversation/group/test_group_candidate_state.py` 检查终态不能被迟到步骤覆盖、持久检查点不能跳步、导演结束与旧条数限制分离，以及失败续接保留已保存的结束决定。事务回滚、版本竞争和执行作用域继续由群聊后台与生成专项覆盖。

`conversation/group/test_group_generation_cleanup.py` 验证仅派发导演调度和 XML 角色生成、空白及旧 JSON 输出一次失败、旧快照可读但内部续接在模型调用前拒绝，以及被删除阶段不能通过旧策略或角色 JSON 参数重新启用。旧格式转换、纠正重试、亲历审查与待回应审查的执行测试已随实现删除。

`conversation/group/test_group_shared_chat.py` 覆盖 A→B→A、A→A→B 回应较早消息、目标权限校验、失败前缀保留与续接；`test_group_turn_plan.py`、`test_group_units.py` 保留旧存储的私密权限与来源边界回归。记忆提纯测试以直接构造的历史权限夹具验证隔离，不再借助旧裁决执行链生成测试数据。离线结果不能代替真实角色卡、模型或移动端验证。

`conversation/group/test_group_units.py` 另覆盖个人投影保留单元类型、其他成员资料不占用用户消息身份、可见窗口的局部顺序，以及首个角色的发言依据不虚构其他发言者。真实交互的改进与残留分别记录在[群聊 M4 验收](../../docs/testing/group-chat/M4_ROUNDS_AND_RECOVERY.md)，离线断言不代表模型语义已全部通过。

`conversation/group/test_group_preview.py` 检查 M3-D 的真实群聊路由、SQLite 只读写入拒绝、预览白名单、H5 静态资源挂载和生命周期禁用；CLI 子进程用本机 HTTP 读取失败前缀，限时退出后端口释放。导演 CLI 专项现覆盖 5 个共同群聊离线场景，包含预期失败和候选版本/终止原因交接。H5 与真机方法见[群聊 M3 联通验收](../../docs/testing/group-chat/M3_DIRECTOR.md)。

`conversation/group/test_group_units.py` 验证 M3-C 用户码点范围、角色单元知情、心理仅作者可见、过滤后窗口、一次状态重放、v2 最终输出契约与世界书输入；同时覆盖调度先落库、审计原子回滚、版本竞争、取消、正常停止及 Outbox 删除回滚。`infrastructure/test_group_units_migration.py` 使用虚构旧库验证原文和权限回填、组合约束、级联、升级失败回滚及有损降级拒绝。内部整轮默认 v2；旧执行权专项显式使用 v1 替身，CLI 的 8 个场景使用 v2。

`conversation/group/test_group_round.py` 验证 M3-B 任务/会话执行令牌、伪造与过期拒绝、整轮模型及采样/历史窗口冻结、调用预算和超时，并用本地 HTTP 200 替身走通默认 SDK 客户端的完整轮次。关闭专项使用真实运行权，验证重复取消时仍等待角色清理和已派发数据库线程，期间拒绝新任务及第二进程运行权。`infrastructure/test_group_model_client.py` 仅连接本地 HTTP 500 替身，检查整轮客户端及 M2 单步调用各只发一次请求、不改普通单聊默认选项，以及客户端清理期间取消不会覆盖已完成结果。分别用统一入口选择对应文件执行，不访问真实模型。

`conversation/group/test_group_director.py` 检查导演调度 JSON、可执行成员、私人基线排除、预算、取消和 revision 竞争；CLI 子进程回放 5 个共同群聊场景到只读 HTTP 报告。`test_group_director_prompts.py` 检查仅允许调度阶段，拒绝已删除阶段，保护本轮前缀及历史预算。两者均使用临时库和模型替身，不代表模型语义通过。

`conversation/group/test_group_round.py` 验证导演与角色两类调用的超时、迟到响应、取消和最终提交；诊断开关或诊断读取失败不改变实际生成终态，取消仍等待线程完成。

`conversation/group/test_group_generation.py` 用假模型检查角色实际收到的完整输入，覆盖秘密与世界书隔离、用户原文、A → B → A、各自状态重放、已确认所选版本、同名身份、缺失知情记录、超长共同背景、无事务外部调用、取消等待持久化、提交失败与迟到结果。含从内部生成到只读轮次 HTTP 的隔离原型；不进入应用 lifespan，不调用真实模型或开发数据库。运行：`python -m tests --group conversation --pattern test_group_generation.py`。

审查回归还检查原文中引号/标签的世界书触发及包装字段不触发、取消后线程失败保持取消、失败标记不可写时保留原始错误或取消。故障只注入临时数据库，不调用真实模型。

`api/test_group_session_routes.py` 同时验证只读轮次鉴权、类型隔离、整轮分页、所选候选和失败前缀；接口样本与路由快照由既有 API 文档回归核对。

`conversation/group/test_group_history.py` 覆盖 M2-A 个人历史的成员/候选/轮次隔离、先过滤后限量、缺失知情记录默认隐藏、内部写入的版本竞争和事务回滚，以及新表随整群删除级联。`infrastructure/test_group_round_migration.py` 验证旧值保留、组合外键、循环引用删除、失败升级回滚和非空降级保护；`test_group_runtime.py` 验证运行权互斥、启动顺序和中断候选只标失败、不重发。测试均使用临时数据库，不调用模型。

M2-A 审查回归还覆盖 autoflush 开/关、未 flush 与已 flush 的调用方修改被拒绝后仍保留；后台 Worker 异常和重复取消关闭时，其他 Worker 与聊天流必须清理后才释放运行权。

`conversation/group/test_group_session_service.py` 验证群聊服务的来源冻结、事务与资源归属，覆盖分支/整理、并发修改、角色删除竞争、取消与大样本导入；`infrastructure/test_group_snapshot_migration.py` 验证快照迁移、来源删除独立和非空降级保护。均使用虚构临时数据，不调用真实模型或 Embedding。

`api/test_session_access_architecture.py` 自动核对全部已注册路由，并用没有业务校验的新接口验证默认拦截。它扫描 `services/` 中同时接受 `db` 和标准资源 ID 参数的公开函数、类方法，验证群聊请求被拒绝且数据不变；共享算法须用 `session_kind_agnostic` 说明例外，群聊专用服务用 `group_session_operation` 声明类型并验证拒绝单聊资源。扫描依赖标准参数命名，不分析任意对象或字典中的隐式引用；自建数据库会话及按任务 ID 调度的后台入口由 `test_group_session_boundary.py` 等专项回归覆盖。

`memory/test_memory_processing_status.py` 验证只读状态接口不入队、故事隔离、排队与运行计数、重试和取消、缺失故事或 Persona，以及捕获成功时间；候选提交时间由 `test_memory_extraction_jobs.py` 覆盖。`infrastructure/test_memory_completion_migration.py` 检查旧任务升级后时间为空，升降级保留任务。均使用临时库和模型替身。

`api/test_api_documentation.py` 校验根 API 总表与真实路由集合一致，并使用真实请求模型校验每个 JSON 请求接口的文档样本。隔离入口将总表和 `scripts/api_documentation.py` 固定清单中的领域契约复制到临时副本的 `project_docs/`，不读取开发配置或本地草稿；检查边界与样本写法见 [API 维护说明](../../docs/api/README.md)。单独运行：`python -m tests --group api --pattern test_api_documentation.py`。

`infrastructure/test_client_initialization.py` 在隔离副本的独立进程中验证导入服务和创建应用不会构造 ChromaDB 或 Embedding 函数，并覆盖并发首次访问复用、构造失败重试、配置传递及记忆集合与 Outbox 调用边界。测试替换资源构造器，不连接真实向量服务。

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

# 只运行 Prompt 子分组
python -m tests --group conversation/prompting

# 只运行群聊业务子分组
python -m tests --group conversation/group

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
| `conversation/prompting/` | 角色卡 Prompt DSL 与示例兼容、完整消息快照、Token 范围估算 |
| `conversation/group/` | 群聊创建、导演、候选、后台恢复、个人可见历史与成员记忆链路 |
| `support/group/` | 共用建库、造数、历史与操作准备、后台模型替身；不包含测试用例 |
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

Prompt 回归集中在 `conversation/prompting/`，保留原有文件名和用例。`python -m tests --group conversation` 和全量入口会递归发现这些测试，单文件仍可配合 `--pattern` 运行。子包需要保留 `__init__.py`，否则标准库发现流程可能漏掉其中的用例。

固定快照继续存放在 `fixtures/`，通过 `tests.FIXTURES_DIR` 定位，避免测试目录深度变化影响文件读取。测试包入口只提供路径，不加载测试类或业务服务。Prompt 测试统一从隔离入口运行，不再修改 `sys.path` 支持直接执行文件。

群聊业务回归集中在 `conversation/group/`，全量与 `conversation` 父分组均递归发现。群聊 HTTP 契约仍在 `api/`，迁移和运行权回归仍在 `infrastructure/`；它们直接引用 `support/group/` 的夹具，不借用业务测试类。固定样本通过 `tests.FIXTURES_DIR` 读取，子进程和预览源码目录通过 `tests.BACKEND_DIR` 定位。

共用群聊夹具按职责拆为 `session_service.py`、`history.py`、`operations.py`、`background.py`、`generation.py`、`units.py` 和 `memory_capture.py`。这些普通类不继承 `unittest.TestCase`，只提供准备及操作方法；实际用例通过混入类或显式引用复用，不从其他测试文件导入夹具。`support/` 由现有隔离入口随整个 `tests/` 复制。

`memory/test_memory_quality_tool.py` 覆盖质量验收工具的隔离启动、固定回放、指标边界、HTML 转义和在线凭据替身，不调用真实模型；样本为 `tests/fixtures/memory_quality_cases.json`。人工审阅用法见 [记忆整理质量验收](../../docs/testing/MEMORY_QUALITY.md)。

`memory/test_event_retention.py` 使用 `tests/fixtures/event_retention_cases.json` 回放八批赠书和四批修表，检查十二项已提取事实线索、三批/容量快照后的事件身份、重启及关闭边界。每批只提供新增片段，最后一批省略旧事实，以“只留最后摘要”为失败对照；输出的保留率不代表真实模型首次提取质量。`infrastructure/test_event_checkpoint_migration.py` 检查阶段外键、旧库升级、回退保留正文和身份删除行为。

`memory/test_memory_write_admission.py` 检查高权重长反应归入事件、图谱下标和消息范围、持续状态及承诺保护、无效/歧义关联、超长保留、相容补全的旧条件与联合来源，以及明确取消不携带旧约定。候选门槛外的有限最近邻回归见 `test_memory_card_extraction.py`；测试均使用替身，不调用真实服务。

`memory/test_graph_memory_consistency.py` 覆盖图谱消息与记忆证据、追加版本、分叉隔离、原数组下标关联、`same/replace`、人工修改/删除、整理后证据保留及原子回滚；`infrastructure/test_graph_evidence_migration.py` 验证旧库升降级保留原行且不猜测来源。优先使用隔离入口，不直接运行会写当前库的 `manual/manual_graph_rag.py`。

自动测试使用 `test_*.py` 命名，放到对应领域目录。测试包的 `__init__.py` 保持轻量，公共夹具按实际复用需求提取，避免在包导入时修改应用配置或启动服务。

`conversation/prompting/test_prompt_compilation_snapshot.py` 对照编译器拆分前保存的 `fixtures/prompt_compilation_snapshots.json`，逐字检查 10 组完整消息的内容、角色和顺序，涵盖角色卡宏、混合示例、分支、动态背景、世界书位置和两种群聊协议。快照来自固定虚构输入，不依赖真实模型；有意调整 Prompt 行为时需审查相应快照差异，不自动覆盖基线。

`conversation/test_context_compression.py` 检查滚动摘要与原文连续覆盖、重启、失败重试、来源修改及删除、取消、外部调用期间无事务、分支冻结和只读状态接口。`infrastructure/test_context_compression_migration.py` 检查旧库升级及降级保留，使用临时库；普通回归不调用真实 LLM。上下文装配现在按摘要覆盖范围保留原文，记忆交接测试继续检查长期提纯资格和原有兼容计算函数。

需要保留现场或使用 IDE 单步调试时，可在准备好独立配置的数据环境中直接运行标准入口，例如 `python -m unittest tests.memory.test_memory_versioning -v`。直接运行 `unittest` 会跳过上述临时工作区隔离。
