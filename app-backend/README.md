# AI Roleplay Backend Engine

[项目说明](../README.md) · [共享 API](../API_TABLE.md) · [文档索引](../docs/README.md)

后端职责边界见 [架构说明](../docs/ARCHITECTURE.md)，数据诊断与重置命令见 [维护工具](scripts/README.md)。

> 基于 FastAPI + SQLite + ChromaDB 构建的私有化部署 AI 角色扮演后端服务。  
> 支持角色深度模拟、长期记忆 RAG 检索、树状分支会话管理、认知与好感度动态演化、多模态 TTS 音频生成以及多候选回复分支机制。

---

## 目录

- [技术栈](#技术栈)
- [核心特性](#核心特性)
- [记忆与上下文机制](#记忆与上下文机制)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [API 参考](#api-参考)
- [目录结构](#目录结构)
- [测试](#测试)
- [注意事项](#注意事项)

---

## 技术栈

| 层级 | 技术 | 作用 |
|------|------|------|
| 网络框架 | FastAPI + Uvicorn | 异步 HTTP / SSE 流式接口 |
| 关系型存储 | SQLAlchemy + SQLite (WAL) | 会话、消息、角色卡、Persona 状态 |
| 向量数据库 | ChromaDB | 长期记忆嵌入存储与相似度检索 |
| 语音合成 | Cloud MIMO-v2.5-tts | 角色配音合成与人声效果渲染 |
| LLM 接入 | OpenAI-compatible API | 对话生成、记忆提纯、认知更新、TTS 文本前处理 |
| 高速匹配 | Aho-Corasick 自动机 | 世界书（Lorebook）关键词触发 |

---

## 核心特性

角色卡中文阅读副本由 `services/character_translation_service.py` 负责，独立缓存在 SQLite `character_translations` 表，通过 Alembic 升级已有数据库；不改写角色原文，也不参与 Prompt。独立的 `llm.translation_model` 未配置时从现有非思考聊天模型初始化一次。使用流程和范围见 [角色卡双版本阅读](../docs/CHARACTER_CARDS.md#原文与中文阅读版本)，HTTP 契约见根目录 API 总表。

### 1. 优化 Prompt Caching 的提示词设计

- **当前角色状态**：同次生成在有明确变化时返回场景及按人物区分的姿势、衣着、位置增量，全部未变化时可省略；支持手动校正和版本冲突保护。当前状态优先于召回的旧背景，候选、删除和分叉按消息边界恢复。详见[角色状态维护](../docs/ROLE_STATE.md)。

- **角色数量中立的 Main RP Prompt**：`{{char}}` 表示当前角色卡或叙事主体，不机械推断卡内逻辑角色数量。单角色卡不会被擅自扩展成群像；单卡若明确声明多个角色、Narrator、Director 或场景主持职责，则允许在同一 assistant 回复中呈现多个受控角色，并要求分别维持身份、目标、知识边界、秘密、人格和语言风格。
- **表达与叙事服从角色卡**：默认主提示词明确只补充角色卡未规定的扮演原则，语气、文风、篇幅、叙事视角和扮演范围由角色卡决定。默认不替用户角色决定台词、思想、情绪或关键行动；用户明确授权代写时，仅在授权范围内描写。这里兼容的是“一张卡内的多个逻辑角色”，项目尚未实现多张独立角色卡参与同一会话的群聊调度。
- **SillyTavern `{{original}}` 兼容**：角色卡 Main Prompt Override 中的 `{{original}}` 表示被覆盖前的默认 Main RP Prompt；角色描述和性格作为独立模块注入，不再冒充 `{{original}}`。
- **结构化示例对话**：非空 `mes_example` 会按 `<START>` 分块，并将 `{{user}}:` / `{{char}}:` 转换为真实的 `user` / `assistant` few-shot 消息后放在对话历史之前；assistant 示例沿用 `<reply>/<status>` 输出契约，示例组末尾再以明确的 system 边界声明其不属于当前剧情，避免模型模仿纯文本格式或把示例事件误当成已经发生的历史；缺失、`null`、空白或只有分隔符时零注入。
- **示例兼容与防重复**：没有 `<START>` 的非空示例按单块兼容，无法识别发言者的内容保守回退为带标签的 system 示例；Main Prompt 或 PHI 已显式使用 `{{mesExamples}}` / `{{mesExamplesRaw}}` 时不再自动注入。
- **PHI 真正后置**：角色卡 `post_history_instructions` 不再混入开头的静态 system，而是在真实历史、动态背景和当前用户消息之后编译为最后一条 system 消息；其中的 `{{original}}` 仍按独立的全局 PHI 语义展开。
- **最终输出契约**：`<reply>/<status>` XML 要求跟随 PHI 放在最后，并排在角色自定义 PHI 之后，降低长历史或示例对最终结构化响应的稀释。该契约只规定完整正文的封装和状态字段，不重复添加扮演范围、发言者区分或用户自主权要求；单一 `status` 暂表示本回合主要互动焦点的情绪，以及角色卡主体与用户之间的总体关系变化。
- **统一容错解析**：流式与非流式回复共用同一份完整响应解析规则，兼容标签缺失、重复嵌套、残缺闭标签以及常见的 `reply/replay` 拼写偏差。SSE 过程只负责增量展示，流结束后始终以完整原文的规范化结果落库；数据库仅保存纯正文，避免坏标签被历史重新包装后持续放大。
- **静态与动态内容分离**：角色设定、性格描述、规范等稳定内容归入开头的 `system`；当前场景、认知状态、好感心情、世界书条目、RAG 召回记忆等当轮背景统一以 XML 标签包裹，放入当前用户消息之前的独立 `system`。
- **动态上下文信任边界**：动态背景带有明确的来源和优先级声明，只作为场景连续性资料，不能覆盖核心角色设定、用户自主权、PHI 或最终输出格式；即使召回内容包含命令式文字，也不会被伪装成用户指令。
- **保留纯净用户原话**：占位符解析后的当前用户消息作为独立 `user` 原样提交，不再附加“当前用户最新消息”包装或检索资料；没有任何动态资料时不会生成空的中间 `system`。
- **明确的消息层次**：使用 `静态 system → 示例 → 历史 → 动态 system（可选）→ 当前 user → PHI system` 结构；末尾 system 已由 DeepSeek 在线验证兼容性。

### 2. 多分支候选回复机制 (Swipe Multi-Replies)

- **多版本生成**：同一轮对话支持生成和存储多个 AI 候选回复版本（Candidates）。
- **活动版本切换**：通过 `/chat/switch_candidate` 接口，可在当前尚未确认的最新用户轮次中设定活动候选（`is_active=True`），同时将其兄弟回复置为 `is_active=False`。
- **下一轮确认**：用户发送下一条消息后，上一轮最终 active 候选即被视为已确认并冻结；修改更早的剧情应创建会话分支，而不是原地切换已经进入长期记忆流程的历史候选。
- **元数据绑定**：每个候选回复版本在数据库中独立绑定其情绪标签（`emotion_tag`）、好感度变动（`affection_change`）以及生成的音频路径（`audio_path`）。切换候选回复时，好感度和情绪指标会自动联动回滚并重算，实现“音画同步、多版本安全切换”。

### 3. 语音合成（TTS）与本地缓存

- **情感与声音事件**：接入云端 MIMO-v2.5-tts API，支持“开心、悲伤、愤怒、温柔、悄悄话、唱歌”等情感，以及“（叹气）、（笑声）、（哭声）、（咳嗽）、[inhale]（吸气）”等声音事件。
- **文本前处理**：
  - **短文本提取、长文本压缩**：使用快速模型（如 `deepseek-v4-flash`）过滤非发音的物理动作、心理活动、场景叙述、其他角色台词和对话前缀。800 字符以内尽量保留原台词；更长输入会保留关键事实和角色口吻，并压缩为最多 500 字符的可播报文本。
  - **结构化质量门槛**：辅助模型默认关闭 thinking（可独立配置），并返回区分 `ok` 与 `no_speech` 的 JSON。截断、空正文、非法结构或长文本未压缩会触发一次强化重试，不能再把失败结果直接发送给 TTS。
  - **声音标签白名单**：只保留受支持的情绪与声音控制标签，动作描述和未知方括号内容不会伪装成音频指令。
  - **安全规则退避**：连续两次 LLM 处理失败时，只保守提取明确引号内或目标角色名前缀后的台词；超长且无法确认说话内容的文本返回“无可安全合成台词”，绝不回退整段原文。
- **本地缓存与重建**：
  - 生成的文件缓存于本地（`data/audio_cache`）。
  - **预处理版本隔离**：缓存键包含 TTS 预处理器版本；提炼规则升级后不会继续命中旧版原文音频。
  - **缓存重建**：再次调用 `POST /utils/tts` 并传入 `message_id` 时，会检查绑定文件是否存在，缺失则重新合成；直接下载缺失文件的限制见根目录 API 文档。
  - **容量清理**：合成完成后启动后台线程检查 MP3 数量，超限时按文件修改时间（mtime）删除最旧的文件；缓存命中不刷新该时间，因此不是严格的 LRU。
- **音频托管**：通过 `/audio/{filename}` 路由下载文件，请求需携带 `X-API-Key`。当前恢复分支仍使用旧文件名格式，不能恢复缺失的 `p2` 版本文件；需重新请求 TTS。长期密钥不接受通过 URL 查询参数传递。

### 4. 数据库自动迁移升级与 Alembic 机制

- **启动期自适应升级**：`application/lifecycle.py` 的 lifespan 启动阶段显式调用 `core/database.py` 中的 `run_migrations()`，使用 Alembic 自动应用新迁移至 `head`。单纯导入数据库模块不会触发迁移。
- **Baseline 自动对齐**：若检测到已存在 `chat_messages` 但没有 `alembic_version`，系统会自动执行 baseline revision 的 stamp 标记，以确保向后兼容与升级的平滑。

### 5. 游标滚动分页历史消息 API

- 会话历史查询接口 `/sessions/{id}/history` 升级支持 `limit`（数量限制）与 `before_id`（游标 ID）参数。
- 前端可按需分段向前分页加载 50 条消息，避免一次性加载过多消息导致移动客户端卡顿，提供更流畅的滚动体验。

### 6. 会话级异步锁

- 使用 `asyncio.Lock` 实现单会话串行处理，避免多请求并发时的写乱序。
- 非流式接口：使用 `try/finally` 确保锁正常释放。
- 流式接口：后台生成 Worker 持有会话锁，与 SSE 连接解耦，断连后继续生成并落库。关闭或重载会取消生成；若已进入写库，则等待保存完成，未完成回合清理结束后再释放数据库会话与锁。
- 历史恢复：历史读取开始或结束时会话仍持锁，则返回 `is_generating=true`；生成在读取期间结束时保守要求客户端再拉取一次最终历史。
- 清理机制：会话删除时自动从锁字典中清理对应条目，防止长期运行占用内存。

### 7. 长期记忆 RAG 检索管道

- 每个角色拥有专属 ChromaDB Collection，按 Persona 隔离存储。
- 进阶祖先链检索：使用单次 SQLite CTE 递归查询，避免 RAG 检索时出现多轮 N+1 查询。
- **三维混合打分精排**：**余弦相似度（60%）+ 内容重要性（20%）+ 时间衰减（20%）**，对父辈及祖先会话条目额外施加代际惩罚权重。
- **图谱证据与版本**：实体、关系追加保存来源消息和记忆依据，按同一故事边界与记忆替代链筛选后执行别名匹配、一至两跳关系召回。人工修改或删除支持记忆后，相应图谱证据失效。无可靠来源的旧图谱行保留但不进入 Prompt，升级不自动补源；详见[图谱与记忆一致性](../docs/GRAPH_MEMORY_CONSISTENCY.md)。
- **共同事实与联合检索**：语义命中卡扩展图谱，回查 SQLite 支持卡，整理来源映射回有效摘要；最终去重并限制最多 16 张、含标签预留共 6000 字符。新自动卡保留消息指纹及故事内时间状态（当前/历史/计划/未明确），Prompt 标注计划尚未兑现。图谱不再另注入重复正文；旧卡不猜测回填，尚无通用冲突裁决或角色知情范围管理。
- 检索权重、半衰期、候选倍数等参数可在 `config.yaml` 中调整。HTTP 热更新仅接受 `schemas.SettingsUpdate` 声明的字段，不能仅凭配置 Schema 的 `dynamic` 标记判断是否对外开放。

### 8. 会话继承树（分叉剧情线）

- 支持从任意历史会话或指定消息节点 fork 出子会话，继承好感度、认知状态、当前场景与心情。
- **分支起始消息自动绑定**：创建分支时，系统会自动复制触发分叉的该条源消息（若未指定则退避到父会话的最后一条激活消息）克隆一份绑定到新分支会话的开头，避免新分支页面呈现空白。
- 删除中间节点时自动将子会话重连到父会话，保持继承链完整。
- RAG 检索支持跨代会话合并，权重随代数增加而衰减。

### 9. 认知与好感度闭环

- **记忆提纯**：对话满足条数阈值后自动触发，LLM 只提炼已经由下一轮用户消息确认的 active 对话；当前用户消息及其候选回复继续保留在短期上下文中，直到用户进入下一轮。SQLite 保存主数据和 Outbox 任务，ChromaDB 作为可重试重建的检索索引。
- **认知更新**：基于高重要性记忆定期更新角色的自我认知状态文本（`cognition_state`）。
- **好感度回滚**：删除 assistant 消息时自动逆向回滚好感值与心情状态。

### 10. SillyTavern Card V2 解析

- 支持 PNG（`tEXt` / `zTXt` / `iTXt`）和 JSON 格式，无需第三方图像库。
- 兼容 V1 / V2 规范及各平台变种字段。
- 展示型字段仍会将常见 HTML 转换为 Markdown；`system_prompt`、Post-History Instructions、示例对话和世界书内容按 Prompt DSL 保真解析。
- 保留 `{{original}}`、`<START>` 以及角色卡作者定义的 XML/伪 XML 结构标签，避免导入阶段破坏主提示词、示例分块和世界书语义。
- `system_prompt_override` 作为兼容别名仅在非空时覆盖标准 V2 `system_prompt` 字段。
- 支持常见的 `extensions.depth_prompt`：读取 `prompt`、`role` 与 `depth`，替换 `{{char}}` / `{{user}}` 后按 SillyTavern 的聊天深度语义注入；数字或字符串角色均可归一化，缺失及畸形配置安全忽略。

### 11. 独立世界书与 SillyTavern 格式兼容 (Independent Lorebook)

- **多数据源载入**：支持为角色独立绑定、加载外部世界书（Lorebooks），或直接使用角色卡自带的设定。
- **SillyTavern 兼容性**：支持解析 SillyTavern 格式的世界书 JSON，支持关键词权重、常量激活、递归扫描等策略。
- **完整位置语义**：保留并执行 `Before/After Char Defs`、`Before/After Example Messages`、`Top/Bottom of Author's Note` 和 `@ Depth`；角色定义前后会真正环绕角色描述，示例位置会编译为 few-shot 消息，作者注释位置映射到本项目动态背景的顶部/底部。
- **深度与消息角色**：`@ Depth` 遵循 Depth 0 位于最后一条聊天消息之后、Depth 1 位于最后一条之前的规则，并支持 `system`、`user`、`assistant` 三种 Chat Completion 角色；相同深度和角色的条目按插入顺序合并。
- **兼容性边界**：旧的 `before_char` / `after_char` 字符串和 SillyTavern 数字位置均可读取；Outlet 名称会保真存储，但在项目尚未提供 `{{outlet::Name}}` 宏解析前不会自动注入。
- **Optional Filter 完整逻辑**：支持 `AND ANY`、`AND ALL`、`NOT ANY`、`NOT ALL` 四种主关键词与可选过滤关键词组合；没有过滤关键词时保持主关键词单独触发的兼容行为。
- **正则关键词**：支持 `/pattern/flags` 形式及 `useRegex` / `use_regex` 字段，兼容 `i`、`m`、`s` 标志；无效正则会被安全忽略，不会回退为可能误触发的普通子串。
- **触发概率**：支持 `probability` 与 `useProbability` / `use_probability`，概率限制在 `0–100`；同一条目在单轮生成中只进行一次概率判定，递归扫描不会反复重掷。
- **字段别名兼容**：内嵌角色卡与独立世界书均可读取 `key/keys`、`keysecondary/secondary_keys`、`disable/enabled`、`caseSensitive/case_sensitive`、`selectiveLogic/selective_logic` 等常见变体。
- **关键词匹配**：利用 **Aho-Corasick（AC自动机）** 算法，在单轮会话中对文本和世界书关键词进行扫描，降低多关键词下的遍历匹配开销。
- **递归扫描与现有 Token 预算**：继续兼容已有的 `scan_depth`、`token_budget` 和递归扫描行为；本次位置语义改造没有新增或调整 Token 淘汰、截断策略。

### 12. 知识图谱双向增强检索 (Graph RAG)

- **实体与关系提取**：记忆提纯时除了沉淀向量文本记忆，还会自动提取实体（Entity）与关系（Relation）三元组写入 SQLite 图关系网络。
- **混合增强 RAG**：在对话检索时，结合向量数据库（ChromaDB）语义匹配与图谱实体关系召回；图谱支持明确别名、分支就近覆盖和真正的两层邻接遍历。
- **异常容错与回滚**：若大模型输出非法格式，自动捕获重试；记忆与向量同步任务由同一 SQLite 事务提交，向量服务短时不可用时持久化退避重试。

### 13. 对话回合事务原子性 (Dialogue State Atomicity)

- **故障自动回滚**：为了避免 SQLite 的写锁定，用户消息先提交入库再触发大模型调用。若之后的 Prompt 装配、大模型 API 调用、SSE 流式解析或回复结果保存发生任何异常，系统会自动在后台触发消息回滚，物理删除该条未作答的用户消息，确保数据库状态的一致性，防止历史对话中留有未回复的用户残留消息。
- **流式对话自愈**：在 `/chat/stream` 生成期间出现异常或前端中断时，该机制同样生效，能同步清理残余状态并释放会话级异步锁。

### 14. 统一大模型适配器层 (Unified LLM Provider)

- **完全解耦解包**：将核心服务（如 `cognition_service` 与 `tts_service`）的第三方 SDK（如直接调用 OpenAI 库）全部解耦，移入适配器层。
- **动态统一调用**：所有对话生成、记忆提炼、情感风格分析均通过 `services/infrastructure/llm_provider.py` 的 `generate` 与 `generate_async` 进行统一封装和动态转发，方便轻松替换底层模型供应商。

---

## 记忆与上下文机制

记忆整理质量可通过 `python -m scripts.memory_quality` 反复验收：默认在临时副本中回放虚构样本，生成 HTML/JSON 报告；实际模型调用须显式使用在线参数。自动规则、字面线索与人工语义结论分开记录，详见 [验收工具](../docs/MEMORY_QUALITY.md)。

记忆库支持用户手动“检查新增与变更”和“重新检查全部”、逐组审阅、应用与撤销。`services/memory/memory_consolidation_service.py` 处理有界模型建议和事务校验，`memory_consolidation_scan.py` 比对原卡指纹并独立记录扫描进度，`memory_visibility.py` 处理原卡/整理结果可见性及分支快照；原卡和来源关联保留，继承卡暂不参与整理。服务启动沿现有迁移链新增整理及扫描进度表，无需清库；旧预览保留，首次增量从未检查开始。仅增量范围内的卡相互比较，不做跨批关联。详细契约见 [记忆 API](../docs/api/MEMORY_API.md#可预览的存量记忆整理)。

本轮维护重点解决了分支时间线泄漏、短长期记忆交接空档、检索查询脱离语境，以及长期记忆切片过碎的问题。当前完整链路如下：

```text
当前分支的有效对话
    → 短期上下文保留
    → 用户进入下一轮，确认上一轮 active 候选
    → 已确认消息到达安全阈值时触发记忆提纯
    → 写入完整、可独立理解的长期记忆卡
    → 使用“当前问题 + 近期语境”执行一次检索
    → 向量记忆与知识图谱共用检索语义
    → 统一装配最终 Prompt
```

### 1. 分支未来消息隔离与分叉点持久化

- `sessions.fork_message_id` 持久化记录真实分叉点，不再根据父会话的“当前最新消息”猜测边界。
- 创建分支时会验证显式 `start_message_id` 确实属于父会话；非法分叉点直接拒绝并回滚。
- 父分支只允许向子分支提供分叉点之前的少量示例，分叉点本身不会重复注入，分叉后的未来消息不会泄漏。
- 旧数据中无法可靠推断分叉点的会话保持 `NULL`，不会冒险回退到父会话最新消息。
- 删除中间分支节点时，子节点会重连到祖父节点，并继承被删除节点原本可信的父级分叉边界。
- 对应迁移：`c6d1e2f3a4b5_add_session_fork_message_id.py`。

### 2. 短期上下文与长期记忆无缝交接

- 记忆提纯触发点会根据短期上下文窗口动态收紧：

  ```text
  effective_trigger = min(
      memory_extract_history_limit,
      context_history_limit - memory_handoff_margin
  )
  ```

- 默认 `context_history_limit=15`、`memory_handoff_margin=2` 时，即使配置的提纯阈值为 20，也会在 13 条未总结消息时提前触发。
- 自动触发计数与实际提纯批次都只包含“严格早于最新 active 用户消息”的内容。当前用户消息及其所有候选不会进入长期记忆；用户发送下一条消息后，上一轮最终 active 候选才获得提纯资格。
- 这种确认机制有意让长期记忆落后一轮。当前轮仍完整存在于短期上下文中，因此不会形成可见的上下文空档，同时避免用户已经拒绝的候选污染长期记忆。
- 后台提纯尚未完成或向量服务暂时失败时，短期历史会临时扩展，继续保留尚未提纯的 active 消息。
- 临时扩展存在批次上限，避免外部服务长期不可用时 Prompt 无限增长；提纯指针推进后自动恢复正常窗口。
- 重新生成回复时会补偿旧 active 回复占用的查询名额，避免边界少取一条消息。

### 3. 上下文化检索查询

- 不再只使用当前用户的一句话执行长期记忆检索。
- 每轮构造一份有界查询：`当前问题 + 最近 N 轮有效对话`，默认承接最近 3 个用户轮次，最多 2400 字符。
- 当前问题优先保留；超长问题保留首尾。选中的历史消息会先公平获得代表性片段，剩余空间再向最新消息倾斜，避免角色长回复把三轮语境挤成一轮。
- 用户消息单条最多保留 320 字符，包含动作与台词的助手回复单条最多保留 640 字符；这里使用字符预算而非精确 Token 预算。
- 只读取当前会话、当前消息之前的 active 用户/助手消息，排除 Swipe 旧回复、其他会话内容和未来消息。
- 向量长期记忆与知识图谱共用同一份语义查询，避免一侧理解指代、另一侧仍脱离上下文。
- 正常情况下每轮只产生一次组合查询，不会对每条历史消息逐条执行向量检索。
- 该机制是“给检索补充近期语境”，不会确定性地把“他/她”改写成人名；真实召回提升仍取决于 Embedding 与图谱匹配质量。

### 4. 长期记忆语义卡片与来源追溯

- 记忆模型被要求按“可独立理解的事实、偏好、关系变化或事件”生成卡片，不再按原始消息逐句切片；语义颗粒度、事实真实性和指代质量仍依赖模型，不是程序能够完全证明的结果。
- 提取提示明确映射 `User → 用户`、`Assistant → 角色名/角色本人`；第三方身份不明确时禁止编造姓名，可以使用“用户提到的妹妹”等有依据的描述。
- 程序写入前过滤寒暄、过短内容、异常结构，以及同时缺少明确主体和地点的明显模糊碎片。较长且包含具体事件的代词卡不再因为以“他/她”开头而一律丢弃。
- 批内只对规范化后完全相同的文本直接去重；不再用模糊字符相似度删除卡片，避免“喜欢/不喜欢”等只差否定词的相反内容被误判为重复。
- 单批最多保留 8 张记忆卡；提示建议单卡不超过 300 字符，程序硬上限为 500 字符。
- 提取输入携带真实消息 ID；每张记忆卡记录最小来源范围：
  - `source_start_message_id`：来源起点。
  - `source_message_id`：兼容原字段，现作为来源终点。
- 程序验证来源端点属于当前提纯批次且起点不晚于终点；非法或缺失时回退为整批范围。范围是否真是支持事实的最小范围仍依赖模型判断。
- 来源范围同时写入 SQLite 与 ChromaDB metadata，并通过记忆列表 API 返回。旧记忆无需强制回填，新字段保持可空。
- 对应迁移：`d7e2f3a4b5c6_add_memory_source_start_message_id.py`。

### 5. 保守的新旧记忆替代

- 向量距离只用于找出最多 3 条值得比较的候选，不再直接触发文本删除或原地合并。
- 快速记忆模型只执行三分类：`same`（实质相同）、`replace`（新表达应成为默认信息）、`coexist`（可以共存或无法确定）。非法输出、超时或模型失败时保守回退为 `coexist`。
- `same` 跳过重复写入；`coexist` 正常新增；`replace` 新建一张卡并通过 `supersedes_id` 指向旧卡，不覆盖旧内容和旧来源。
- 默认检索在当前 Persona 继承链内隐藏已被替代的旧卡。子分支替代祖先记忆不会修改祖先记录，因此父分支和兄弟分支仍可继续使用原记忆。
- 检索侧只直接去除规范化后完全相同的内容；“喜欢/不喜欢”“已经/尚未”等高字面相似但语义相反的记忆不会再被字符相似度误删。
- 这里只实现面向 Prompt 的轻量替代关系，不引入当前/历史/计划/取消状态机、事实槽位、有效时间或复杂历史查询。
- 对应迁移：`f8a3b4c5d6e7_add_memory_supersedes_id.py`。API 字段见根目录的 [API 总表](../API_TABLE.md)，记忆规则详见 [记忆模块 API](../docs/api/MEMORY_API.md)。

### 6. 向量 Outbox、故障降级与离线回归

- 向量库计数或检索失败时，长期记忆召回安全降级为空，不阻断正常对话。
- 时间衰减以当前剧情分支内、来源消息之后的有效用户消息数为轮次；父线分叉后的消息、兄弟分支、其他会话、assistant 回复和 inactive 消息均不推进该年龄。手动添加且没有来源消息的记忆不施加时间衰减。
- `retrieval_max_distance=0` 只接受距离恰为 0 的候选；负数配置安全返回空结果，避免除零或意外放宽召回。
- 自动提纯、手动新增和手动修改都先在同一个 SQLite 事务中保存记忆及 `upsert_vector` 任务；SQLite 提交失败时两者一同回滚，ChromaDB 不会被提前修改。
- Outbox worker 以稳定的 `mem_{memory_id}` 文档 ID 执行幂等 `upsert`。向量服务失败时任务保留并指数退避；一次重试周期耗尽后冷却再试，不丢弃任务。
- 角色删除与头像替换会在同一个 SQLite 事务中登记 `delete_avatar` 任务，由 Outbox 异步回收旧文件；清理器仅允许删除配置的受管头像目录内文件，仍被其他角色引用、路径越界或已经不存在的文件均会安全跳过。
- `processing` 任务使用 5 分钟租约；worker 在向量写入后异常退出时，租约到期可自动恢复并安全重放。过期的新增任务若发现 SQLite 记忆已被删除，只会清理对应向量，不会复活旧记忆。
- 正常情况下后台 worker 每 5 秒轮询并尽快同步；短暂延迟或向量服务故障期间，SQLite 记忆仍是权威数据，但该记忆可能尚未参与向量召回。
- 短期交接窗口在提纯失败期间继续兜底，并受到批次上限保护。
- 新增完全离线的 SQLite 与函数替身测试，不需要访问对话模型、Embedding API 或真实 ChromaDB。

> 当前范围说明：长期记忆是低优先级的 Prompt 辅助信息，不是事实数据库或人脑模拟。近期有效对话始终比长期记忆更接近当前状态；本轮只解决明显的新旧信息默认选择问题。

### 7. Prompt Token 范围观测

- `GET /sessions/{session_id}/compile_prompt` 在原有 `messages` 外返回 `token_estimate`，提供总字符数、Token 估算值、宽松上下界和各上下文区段占用。
- 统计直接基于最终实际发送格式的 messages，区分角色设定、近期历史、场景、认知、状态、世界书、长期记忆、图谱和当前问题。
- 当前使用无需额外依赖的混合中英文启发式估算，结果明确标记为非精确值，不用于计费核算。
- 正常聊天装配会输出不含 Prompt 正文的 `[PROMPT METRICS]` 汇总日志，便于观察真实角色卡和对话的体积分布。
- 第一版只做观测，不裁剪 Prompt、不设置全局硬预算，也不为缓存冻结或改变检索结果。

### 8. 轻量 Graph RAG 质量修复

- `GraphEntity.aliases` 保存可选的明确昵称和简称；写入时进行 Unicode、大小写和重复规范化，并拒绝“他/她/它/这里/那个”等通用代词。旧实体的别名字段允许为空，无需回填。
- 检索先把 Persona 继承链中的写时复制实体折叠为名称级有效图。同名实体和相同三元组由离当前分支最近的记录覆盖祖先记录，不再把新旧描述持续用分号拼接。
- 2-hop 改为真正的两层邻接遍历：`A → B → C` 查询 A 时可以召回 B→C，但不会继续召回第三层；关系遍历可双向到达，输出仍保留原始方向。
- “用户”和当前角色名继续作为高连接枢纽受到扩展限制，避免从通用节点把整张关系网注入 Prompt。
- 关系按 hop、分支代际、重要性和稳定次级键确定性排序，继续服从 `graph_min_importance` 与 `graph_max_relations`。
- 本轮没有引入图谱时态状态机、LLM 查询时消歧、图向量或新图数据库。对应迁移：`a9b8c7d6e5f4_add_graph_entity_aliases.py`。

---

## 快速开始

以下命令均在仓库的 `app-backend/` 目录中执行。从仓库根目录进入：

```bash
cd app-backend
```

### 1. 安装依赖

```bash
python -m venv venv
# Windows
venv\Scripts\activate
# macOS / Linux
source venv/bin/activate

pip install -r requirements.txt
```

### 2. 配置环境变量

在后端目录 `app-backend/` 中创建 `.env` 文件（不是仓库根目录）：

```dotenv
# 对话模型的 API Key
CHAT_API_KEY=sk-xxxxxxxxxxxxxxxx

# Embedding 模型的 API Key（可与 CHAT_API_KEY 相同）
EMBEDDING_API_KEY=sk-xxxxxxxxxxxxxxxx

# 小米 MiMo 语音合成 API Key
MIMO_API_KEY=sk-xxxxxxxxxxxxxxxx

# 公网访问保护密钥（留空则本地开发免鉴权）
ACCESS_API_KEY=
```

### 3. 修改模型配置

首次配置可复制 [config.yaml.example](config.yaml.example) 为 `config.yaml`（PowerShell：`Copy-Item config.yaml.example config.yaml`），再替换示例中的聊天/嵌入 API 地址与模型 ID。已有配置请先备份后合并，不要覆盖。示例仅列常用字段，不含密钥；密钥继续放在 `.env` 中，语音功能在示例中默认关闭。

创建或编辑本地 `config.yaml`（见下方[配置说明](#配置说明)），至少填写 `chat_base_url` 和模型名称。可以只填写需要覆盖的配置项，启动时会自动补齐其余字段；文件不存在时会自动生成默认配置，但仍需按实际服务修改连接和模型。

`config.yaml` 仅在本地保存，已从 Git 跟踪中移除并由后端 `.gitignore` 忽略。配置默认值和升级规则维护在 `core/config.py` 的 `CONFIG_SCHEMA` 与迁移逻辑中；新增字段自动补齐并回写，保留已有配置值。

### 4. 启动服务

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

启动后终端会打印本机局域网 IP，供手机/其他设备在同一 Wi-Fi 下访问。

本地调试若需要通过 8080 访问已运行的 8000 服务，可在后端目录另开终端运行 `python port_forward_8080.py`。该工具仅监听 `127.0.0.1:8080`，转发至 `127.0.0.1:8000`，不会启动后端或修改其配置；按 Ctrl+C 停止。Windows 未激活虚拟环境时使用 `.\venv\Scripts\python.exe`。

---

## 配置说明

所有非敏感配置集中在 `config.yaml`，修改后重启生效；部分参数也可通过 `PUT /utils/settings` API 热更新并自动持久化。

```yaml
llm:
  default_chat_model: deepseek-flash           # 默认模型，与思考开关独立
  chat_model: deepseek-v4-pro                  # 旧客户端思考模型槽
  non_reasoning_chat_model: deepseek-v4-flash  # 旧客户端非思考模型槽
  model_profiles: []                          # id / label / adapter
  memory_thinking_mode: disabled
  memory_reasoning_effort: high
  tts_preprocess_model: deepseek-flash
  tts_thinking_mode: disabled
  tts_reasoning_effort: high
  memory_model: deepseek-v4-flash              # 记忆提纯专用模型
  embedding_model: doubao-embedding-vision-251215
  chat_base_url: https://api.deepseek.com/v1
  embedding_base_url: https://ark.cn-beijing.volces.com/api/v3
  temperature: 0.7
  memory_temperature: 0.3
  max_tokens: 4096
  reasoning_mode: false                        # 默认模型的思考开关，不再切换模型
  timeout: 60                                  # LLM 请求超时秒数
  top_p: 1.0
  presence_penalty: 0.0
  frequency_penalty: 0.0
  repetition_penalty: 1.0
  reasoning_effort: high

app:
  context_history_limit: 15                    # 注入 LLM 的最近对话条数
  retrieval_top_k: 3                           # RAG 最终召回条数
  retrieval_context_turns: 3                   # 构造检索查询时承接的最近用户轮数
  retrieval_query_max_chars: 2400              # 上下文化检索查询字符预算
  memory_extract_history_limit: 20             # 记忆提纯扫描的历史条数上限
  memory_handoff_margin: 2                     # 短期窗口淘汰前预留的提纯缓冲消息数
  retrieval_min_importance: 0.3                # 记忆重要性过滤阈值（0~1）
  retrieval_max_distance: 1.2                  # 向量余弦距离上限；0 仅允许精确距离，负数禁用本轮召回
  cognition_update_interval: 30                # 认知更新触发间隔（消息条数）
  cognition_importance_threshold: 0.8          # 触发认知更新所需的记忆重要性门槛
  cognition_max_words: 200                     # 认知状态文本最大字数
  lorebook_scan_depth: 5                       # Lorebook 扫描最近 N 条消息
  lorebook_token_budget: 3000                  # Lorebook 注入 Token 总预算
  lorebook_max_recursive_passes: 3             # Lorebook 递归触发最大轮数

  # 混合打分权重（三项之和建议为 1.0）
  retrieval_weight_similarity: 0.6
  retrieval_weight_importance: 0.2
  retrieval_weight_time: 0.2
  retrieval_half_life_turns: 50                # 时间衰减半衰期（轮次）
  retrieval_candidate_multiplier: 3            # 粗排候选数 = top_k × multiplier
  retrieval_ancestor_weight: 0.8               # 父代记忆的权重衰减系数
  dedup_write_threshold: 0.15                  # 写时关系判断候选的向量距离门槛
  graph_min_importance: 0.5                    # 图谱检索关系过滤最低重要性
  graph_max_relations: 12                      # 图谱检索单次最大装填关系数量

  # 存储路径
  sqlite_db_path: data/data.db
  chroma_db_path: data/chroma_data
  upload_avatar_dir: ./assets/avatars

  # 安全与限制
  cors_origins:
    - "*"                                      # 预留的 CORS 配置；当前应用工厂仍允许所有 Origin
  max_card_size_mb: 10

  # 历史消息拉取
  history_fetch_default: 50
  history_fetch_max: 500

tts:
  enabled: true                                # 是否启用 TTS 语音播报
  base_url: "https://api.xiaomimimo.com/v1"    # MIMO API 地址
  model: "mimo-v2.5-tts"                       # 合成模型
  default_voice: "冰糖"                        # 默认角色音色
  cache_dir: "data/audio_cache"                # 音频缓存本地文件夹
  max_cache_files: 500                         # 按修改时间清理缓存的最大文件数
```

### 动态可调参数（通过 `PUT /utils/settings` 无需重启）

以下列表以 `schemas.SettingsUpdate` 为准。检索打分权重、祖先权重、去重阈值和图谱阈值目前不属于 HTTP 更新接口的字段，应修改 YAML 后重启。

`temperature` · `max_tokens` · `reasoning_mode` · `context_history_limit` ·  
`memory_handoff_margin` · `retrieval_top_k` · `retrieval_context_turns` ·
`retrieval_query_max_chars` · `retrieval_min_importance` · `retrieval_max_distance` ·
`lorebook_scan_depth` · `lorebook_token_budget` · `lorebook_max_recursive_passes` ·  
`cognition_max_words` · `retrieval_half_life_turns` · `retrieval_candidate_multiplier` ·  
`top_p` · `presence_penalty` · `frequency_penalty` · `repetition_penalty` · `reasoning_effort`

---

## API 参考

完整请求、响应和前后端契约统一维护在根目录的 [API 总表](../API_TABLE.md)，记忆筛选、继承和故事导航规则见 [记忆模块 API](../docs/api/MEMORY_API.md)。

> 业务 API 在 `.env` 中设置 `ACCESS_API_KEY` 后需携带 `X-API-Key: <your_key>`。静态头像 `/assets/avatars/*` 公开访问；内置 `/docs`、`/redoc` 和 `/openapi.json` 目前也未受该依赖保护。
>
> 不再支持通过 `?api_key=` 或 `?token=` 传递长期密钥，避免密钥进入访问日志、浏览器历史或 Referer。
>
> 本地开发时留空 `ACCESS_API_KEY` 即可免鉴权。

### 静态资源认证约定

- **头像**：`/assets/avatars/{filename}` 是公开静态地址，图片组件可以直接访问，不需要认证请求头。接口中的 `avatar_path` 应为该公开资源的相对路径，或无需客户端长期密钥的短期签名绝对 URL；不得在头像 URL 中拼接长期 API Key。
- **音频**：后端返回 `/audio/{filename}` 相对 URL。该资源不是公开静态文件，客户端必须使用带 `X-API-Key` 请求头的下载请求获取临时文件后播放。
- **外部绝对 URL**：后端若返回外部绝对资源 URL，该 URL 必须本身公开或为短期签名地址，客户端不会向外部域名发送本后端的长期 API Key。

各业务端点的路径、分页参数、请求和响应示例统一见 [API 总表](../API_TABLE.md)，本页不再重复维护接口表。

---

## 目录结构

```
app-backend/
├── main.py                  # ASGI 入口：app = create_app()
├── config.yaml              # 自动生成的本地运行时配置（Git 忽略）
├── .env                     # 敏感密钥（不提交）
├── requirements.txt
├── application/
│   ├── factory.py           # 应用、CORS、静态资源与路由装配
│   ├── lifecycle.py         # 数据库迁移与 Outbox 任务生命周期
│   └── banner.py            # 启动地址提示
├── scripts/
│   ├── README.md            # 显式维护命令说明
│   ├── query_db.py          # 数据库概览
│   ├── query_session_messages.py # 会话消息查询
│   └── clear_db.py          # 数据重置（保留原有终端确认）
│
├── core/
│   ├── models.py            # SQLAlchemy ORM 模型定义
│   ├── database.py          # 数据库连接、Session 工厂与迁移函数（由 lifespan 调用）
│   ├── config.py            # Settings 类，加载 .env + config.yaml
│   ├── auth.py              # X-API-Key 鉴权依赖
│   ├── locking.py           # 会话级 asyncio.Lock 锁管理
│   └── utils.py             # 工具函数（获取本机 IP 等）
│
├── routers/                 # 路由层 (轻量级，仅负责 HTTP 路径定义、参数校验与异常封装，具体业务委托给 services)
│   ├── chat.py              # /chat 与 /chat/stream 及 /chat/switch_candidate
│   ├── sessions.py          # /sessions 端点（分页历史、消息/记忆管理、调试等）
│   ├── characters.py        # /characters 端点
│   ├── lorebooks.py         # /lorebooks 端点（导入、详情、编辑、绑定等）
│   ├── audio.py             # 受鉴权保护的音频下载
│   └── utils.py             # /upload/avatar 与 /utils/tts 端点
│
├── services/                # 业务服务层 (高内聚核心业务逻辑，分包管理)
│   ├── media/
│   │   └── audio_service.py # 音频文件查找与旧格式恢复
│   ├── conversation/        # 对话与会话相关业务服务
│   │   ├── chat_engine.py   # LLM 执行引擎（大模型请求参数合并与响应结构化解析）
│   │   ├── chat_turn_service.py # 对话回合控制服务（管理锁回滚、SSE 等事务边界）
│   │   ├── context_assembler.py # 对话上下文装配服务（装配检索、对话历史等拼装 Prompt）
│   │   ├── message_service.py # 消息生命周期管理服务
│   │   ├── prompt_compiler.py # Prompt 拼装与格式规整编译器
│   │   ├── prompt_token_estimator.py # 启发式 Prompt Token 范围估算服务
│   │   ├── retrieval_query_service.py # 上下文化检索查询生成器
│   │   └── session_service.py # 会话生命周期与分支状态拷贝/回滚服务
│   ├── infrastructure/      # 底层基础设施与服务客户端
│   │   ├── clients.py       # Chroma/SQLite 客户端连接管理
│   │   ├── llm_logger.py    # LLM 输入输出专门调试日志器
│   │   ├── llm_provider.py  # 统一大模型服务适配器接口（解耦 SDK 调用）
│   │   └── outbox_worker.py # 发件箱后台异步任务处理器（向量同步、音频/头像清理与延迟退避）
│   ├── lorebook/            # 世界书引擎
│   │   ├── ahocorasick.py   # Aho-Corasick AC自动机快速多词匹配算法
│   │   ├── lorebook_engine.py # 世界书加载、递归扫描与 Token 预算裁剪引擎
│   │   └── parse_lorebook.py # SillyTavern 格式世界书 JSON 导入与解析
│   ├── memory/              # 记忆与知识图谱相关服务
│   │   ├── cognition_service.py # Persona 认知更新服务
│   │   ├── graph_service.py # 知识图谱 Graph RAG 增强关系检索服务
│   │   ├── memory_extraction_service.py # 长期记忆提取、剪裁与来源范围限制服务
│   │   ├── memory_manager.py # RAG 检索粗排与精排计算、记忆库接口层外观模式（Facade）
│   │   ├── persona_lineage.py # Persona 继承树追溯与分支 turn 计算服务
│   │   ├── session_memory_query_service.py # 记忆分页、分类统计与角色故事导航
│   │   └── session_memory_service.py # 会话专属记忆管理服务
│   ├── character_service.py # 角色卡增删改查业务服务
│   ├── parse.py             # SillyTavern 角色卡解析与清洗
│   └── tts_service.py       # TTS 文本预处理与音频缓存自愈重建服务
│
├── schemas.py               # Pydantic 请求/响应模型
├── alembic.ini              # Alembic 数据库迁移配置文件
├── alembic/                 # Alembic 数据库迁移版本控制目录
│
├── tests/                   # 按职责分组的自动回归与手动场景
│   ├── __main__.py          # python -m tests：临时工作区运行入口
│   ├── README.md            # 测试指南与新增约定
│   ├── api/                 # 接口、鉴权与路由服务边界
│   ├── conversation/        # Prompt、分叉、对话回合和上下文
│   ├── memory/              # 提纯、版本、检索与图谱
│   ├── infrastructure/      # 迁移、资源清理、Embedding 与 Outbox
│   ├── core/                # 配置系统
│   ├── lorebook/            # 世界书规则
│   ├── parsing/             # 回复解析
│   ├── tts/                 # 语音文本预处理
│   └── manual/              # 显式运行的旧式场景与真实服务抽查
│
└── data/
    ├── data.db              # SQLite 关系型数据库文件 (WAL 模式)
    ├── chroma_data/         # ChromaDB 向量文件夹
    └── audio_cache/         # 合成音频文件本地缓存目录 (.mp3)
```

---

## 测试

在后端目录使用当前虚拟环境运行：

```bash
python -m tests
python -m tests --group memory
python -m tests --group conversation --pattern test_branch_context_boundary.py
```

Windows 未激活环境时使用 `.\venv\Scripts\python.exe -m tests`。

GitHub Actions 在 Python 3.12 / Ubuntu 24.04 上运行同一隔离入口；配置与排查见[持续集成说明](../docs/CI.md)。

入口会创建临时工作区、临时数据库和服务配置，再执行自动回归；不会复制日常开发的密钥或数据。需要真实模型、持久数据库或本地角色卡的场景保留在 `tests/manual/`，不参与默认发现。

目录职责、调试方式和手动脚本的使用边界统一维护在 [测试指南](tests/README.md)。

---

## 注意事项

- **保守 CHARX 导入**：`app.max_charx_size_mb` 默认 20 MiB，独立于 PNG/JSON 和头像限制，修改后重启生效。请求体解析前鉴权与累计限流量，只允许一个文件、最多三个并发上传；ZIP 条目校验失败也消耗预算并缓存。显式 CCv3 导入计划报告兼容性，创建角色与追加素材分开约束。素材按内容去重，新增摘要迁移并保留旧库升级链。单进程服务最多三个预览，有效期 15 分钟；lifespan 每 60 秒清理过期文件。保存响应丢失可查询回执恢复结果。固定大小、像素、状态与错误码见根目录 API 总表。

- **手动多立绘**：`services/media/character_portraits.py` 管理独立图片资源与剧情节点选择；新增 `character_portraits`、Persona 初始选择和消息选择列，通过 Alembic 升级保留旧卡旧故事。图片用 Pillow 校验 PNG/JPEG/WebP 内容、大小和像素数，存入既有头像资源目录；删除沿用 Outbox 并复核头像和立绘引用。无额外资源时沿用头像，不触发情绪、开场或脚本规则。HTTP 契约见根目录 API 总表。

- **单用户私有部署限制**：本项目为单用户私有部署设计，未隔离多租户的数据库与 ChromaDB 集合。如果在公网或多端部署，请务必在 `.env` 中指定 `ACCESS_API_KEY` 以保护接口安全。
- **密钥传输边界**：长期 `ACCESS_API_KEY` 只允许放在 `X-API-Key` 请求头中，禁止拼接到头像、音频或其他 URL。生产环境还必须启用 HTTPS，避免请求头在传输途中被窃听。
- **缺失音频恢复**：重新请求 `POST /utils/tts` 并传入原 `message_id`、音色和语速可重新生成。直接下载缺失的版本化文件目前返回 `404`，不能承诺透明恢复；详见根目录 API 文档。
- **历史分页性能**：通过 `/sessions/{id}/history` 查询历史记录时，参数 `before_id` 可作为分页游标，强烈建议前端在聊天页初始化时分步拉取（如每次获取 50 条），并在滚动触顶时按需往前拉取，避免长会话引起的内存暴涨。
- **删除接口兼容**：角色、会话、消息和世界书删除提供 `DELETE` 与 `POST .../delete` 两种路径。记忆删除目前只有 `DELETE /sessions/{session_id}/memories/{memory_id}`，没有 POST 别名。

CHARX 安全回归：`python -m tests --group infrastructure --pattern test_charx_upload.py` 覆盖鉴权前零读取、声明/流式总量限制、并发及空闲超时；`python -m tests --group parsing --pattern test_charx_import.py` 覆盖解析预算、去重、兼容计划、回执恢复和共享文件回收。

CHARX 动图按原始字节保留 GIF/APNG/WebP，预览仅展示静态首帧；后端逐帧校验，单图最多 300 帧，所有帧计入累计 2.5 亿像素预算。播放效果需按客户端验收。
