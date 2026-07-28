# AI Roleplay Backend Engine

> 基于 FastAPI + SQLite + ChromaDB 构建的私有化部署 AI 角色扮演后端服务。  
> 支持角色深度模拟、长期记忆 RAG 检索、树状分支会话管理、认知与好感度动态演化、多模态 TTS 音频生成以及多候选回复分支机制。

---

## 目录

- [技术栈](#技术栈)
- [核心特性](#核心特性)
- [近期记忆与上下文增强](#近期记忆与上下文增强2026-07)
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

### 1. 优化 Prompt Caching 的提示词设计

- **角色数量中立的 Main RP Prompt**：`{{char}}` 表示当前角色卡或叙事主体，不机械推断卡内逻辑角色数量。单角色卡不会被擅自扩展成群像；单卡若明确声明多个角色、Narrator、Director 或场景主持职责，则允许在同一 assistant 回复中呈现多个受控角色，并要求分别维持身份、目标、知识边界、秘密、人格和语言风格。
- **叙事视角服从角色卡**：不再强制第一人称，由角色卡、示例和既有历史决定采用第一人称、第三人称或混合叙事；多角色正文必须使用清晰的台词归属、动作和必要旁白，同时继续禁止替用户角色决定台词、思想、情绪或关键行动。这里兼容的是“一张卡内的多个逻辑角色”，项目尚未实现多张独立角色卡参与同一会话的群聊调度。
- **SillyTavern `{{original}}` 兼容**：角色卡 Main Prompt Override 中的 `{{original}}` 表示被覆盖前的默认 Main RP Prompt；角色描述和性格作为独立模块注入，不再冒充 `{{original}}`。
- **结构化示例对话**：非空 `mes_example` 会按 `<START>` 分块，并将 `{{user}}:` / `{{char}}:` 转换为真实的 `user` / `assistant` few-shot 消息后放在对话历史之前；assistant 示例沿用 `<reply>/<status>` 输出契约，避免模型模仿纯文本示例而破坏结构化响应；缺失、`null`、空白或只有分隔符时零注入。
- **示例兼容与防重复**：没有 `<START>` 的非空示例按单块兼容，无法识别发言者的内容保守回退为带标签的 system 示例；Main Prompt 或 PHI 已显式使用 `{{mesExamples}}` / `{{mesExamplesRaw}}` 时不再自动注入。
- **PHI 真正后置**：角色卡 `post_history_instructions` 不再混入开头的静态 system，而是在真实历史、动态背景和当前用户消息之后编译为最后一条 system 消息；其中的 `{{original}}` 仍按独立的全局 PHI 语义展开。
- **最终输出契约**：`<reply>/<status>` XML 要求跟随 PHI 放在最后，并排在角色自定义 PHI 之后，降低长历史或示例对最终结构化响应的稀释。`reply` 可包含旁白及一个或多个受控角色的台词；单一 `status` 暂表示本回合主要互动焦点的情绪，以及角色卡主体与用户之间的总体关系变化。
- **静态与动态内容分离**：角色设定、性格描述、规范等稳定内容归入开头的 `system`；当前场景、认知状态、好感心情、世界书条目、RAG 召回记忆等当轮背景统一以 XML 标签包裹，放入当前用户消息之前的独立 `system`。
- **动态上下文信任边界**：动态背景带有明确的来源和优先级声明，只作为场景连续性资料，不能覆盖核心角色设定、用户自主权、PHI 或最终输出格式；即使召回内容包含命令式文字，也不会被伪装成用户指令。
- **保留纯净用户原话**：占位符解析后的当前用户消息作为独立 `user` 原样提交，不再附加“当前用户最新消息”包装或检索资料；没有任何动态资料时不会生成空的中间 `system`。
- **明确的消息层次**：使用 `静态 system → 示例 → 历史 → 动态 system（可选）→ 当前 user → PHI system` 结构；末尾 system 已由 DeepSeek 在线验证兼容性。

### 2. 多分支候选回复机制 (Swipe Multi-Replies)

- **多版本生成**：同一轮对话支持生成和存储多个 AI 候选回复版本（Candidates）。
- **活动版本切换**：通过 `/chat/switch_candidate` 接口，可自由设定某一条候选回复为活动状态（`is_active=True`），同时将其兄弟回复置为 `is_active=False`。
- **元数据绑定**：每个候选回复版本在数据库中独立绑定其情绪标签（`emotion_tag`）、好感度变动（`affection_change`）以及生成的音频路径（`audio_path`）。切换候选回复时，好感度和情绪指标会自动联动回滚并重算，实现“音画同步、多版本安全切换”。

### 3. 语音合成（TTS）与 LRU 缓存机制

- **情感与声音事件**：接入云端 MIMO-v2.5-tts API，支持“开心、悲伤、愤怒、温柔、悄悄话、唱歌”等情感，以及“（叹气）、（笑声）、（哭声）、（咳嗽）、[inhale]（吸气）”等声音事件。
- **文本前处理**：
  - **文本预处理**：使用快速模型（如 `deepseek-v4-flash`）对角色发言进行预处理，过滤非发音的物理动作、心理活动、场景叙述和对话前缀，保留实际说话内容。
  - **声音标记保护**：过滤前对声音事件标记进行暂存保护，过滤完毕后还原，保留声音细节。
  - **正则规则退避**：在 LLM API 故障时自动回退到正则规则过滤。
- **LRU 缓存与重建**：
  - 生成的文件缓存于本地（`data/audio_cache`）。
  - **缓存重建**：播放请求到达时，如果本地物理文件不存在但数据库中有记录，会自动触发重新合成，避免播放失败。
  - **LRU 清理**：由后台线程监控缓存文件总数，超限时自动清理较旧的音频。
- **音频托管**：通过自定义 `/audio/{filename}` 路由提供音频文件；客户端需要先用携带 `X-API-Key` 请求头的下载请求取得临时文件，再交给播放器播放。该路由同时负责缓存文件丢失后的延迟自愈重建，不接受 URL 查询参数中的长期密钥。

### 4. 数据库自动迁移升级与 Alembic 机制

- **启动期自适应升级**：FastAPI 执行 startup 回调时，会显式调用 `core/database.py` 中的 `run_migrations()`，使用 Alembic 扫描并自动应用所有新迁移升级（通过 `command.upgrade` 直达 `head` 版本）。单纯导入数据库模块不会触发迁移。
- **Baseline 自动对齐**：若检测到已存在 `chat_messages` 但没有 `alembic_version`，系统会自动执行 baseline revision 的 stamp 标记，以确保向后兼容与升级的平滑。

### 5. 游标滚动分页历史消息 API

- 会话历史查询接口 `/sessions/{id}/history` 升级支持 `limit`（数量限制）与 `before_id`（游标 ID）参数。
- 前端可按需分段向前分页加载 50 条消息，避免一次性加载过多消息导致移动客户端卡顿，提供更流畅的滚动体验。

### 6. 会话级异步锁

- 使用 `asyncio.Lock` 实现单会话串行处理，避免多请求并发时的写乱序。
- 非流式接口：使用 `try/finally` 确保锁正常释放。
- 流式接口：锁的生命周期绑定到 SSE `StreamingResponse` 的 `finally` 块，防止并发请求导致写入乱序。
- 清理机制：会话删除时自动从锁字典中清理对应条目，防止长期运行占用内存。

### 7. 长期记忆 RAG 检索管道

- 每个角色拥有专属 ChromaDB Collection，按 Persona 隔离存储。
- 进阶祖先链检索：使用单次 SQLite CTE 递归查询，避免 RAG 检索时出现多轮 N+1 查询。
- **三维混合打分精排**：**余弦相似度（60%）+ 内容重要性（20%）+ 时间衰减（20%）**，对父辈及祖先会话条目额外施加代际惩罚权重。
- **图谱关联召回**：与 **Graph RAG** 关系提取相匹配，召回时混合查询数据库事实三元组，获得更精准的事实一致性上下文。
- 检索权重、半衰期、候选倍数等参数均可在 `config.yaml` 中调整；其中标记为动态可调的参数还可通过 API 热更新，无需重启。

### 8. 会话继承树（分叉剧情线）

- 支持从任意历史会话或指定消息节点 fork 出子会话，继承好感度、认知状态、当前场景与心情。
- **分支起始消息自动绑定**：创建分支时，系统会自动复制触发分叉的该条源消息（若未指定则退避到父会话的最后一条激活消息）克隆一份绑定到新分支会话的开头，避免新分支页面呈现空白。
- 删除中间节点时自动将子会话重连到父会话，保持继承链完整。
- RAG 检索支持跨代会话合并，权重随代数增加而衰减。

### 9. 认知与好感度闭环

- **记忆提纯**：对话满足条数阈值后自动触发，LLM 提炼近期对话为结构化记忆条目；SQLite 保存主数据和 Outbox 任务，ChromaDB 作为可重试重建的检索索引。
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

## 近期记忆与上下文增强（2026-07）

本轮维护重点解决了分支时间线泄漏、短长期记忆交接空档、检索查询脱离语境，以及长期记忆切片过碎的问题。当前完整链路如下：

```text
当前分支的有效对话
    → 短期上下文保留
    → 到达安全阈值前触发记忆提纯
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
- 对应迁移：`f8a3b4c5d6e7_add_memory_supersedes_id.py`。API 字段见 `API_TABLE.md`。

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

在项目根目录创建 `.env` 文件：

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

编辑 `config.yaml`（见下方[配置说明](#配置说明)），至少填写 `chat_base_url` 和模型名称。

### 4. 启动服务

```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

启动后终端会打印本机局域网 IP，供手机/其他设备在同一 Wi-Fi 下访问。

---

## 配置说明

所有非敏感配置集中在 `config.yaml`，修改后重启生效；部分参数也可通过 `PUT /utils/settings` API 热更新并自动持久化。

```yaml
llm:
  chat_model: deepseek-v4-pro                  # 主（思考）模型
  non_reasoning_chat_model: deepseek-v4-flash  # 快速（非思考）模型，兼用于 TTS 文本预处理
  memory_model: deepseek-v4-flash              # 记忆提纯专用模型
  embedding_model: doubao-embedding-vision-251215
  chat_base_url: https://api.deepseek.com/v1
  embedding_base_url: https://ark.cn-beijing.volces.com/api/v3
  temperature: 0.7
  memory_temperature: 0.3
  max_tokens: 4096
  reasoning_mode: false                        # true → 默认使用思考模型
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
    - "*"                                      # 预留的 CORS 配置；当前 main.py 仍允许所有 Origin
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
  max_cache_files: 500                         # LRU 缓存淘汰的最大文件数
```

### 动态可调参数（通过 `PUT /utils/settings` 无需重启）

`temperature` · `max_tokens` · `reasoning_mode` · `context_history_limit` ·  
`memory_handoff_margin` · `retrieval_top_k` · `retrieval_context_turns` ·
`retrieval_query_max_chars` · `retrieval_min_importance` · `retrieval_max_distance` ·
`lorebook_scan_depth` · `lorebook_token_budget` · `lorebook_max_recursive_passes` ·  
`cognition_max_words` · `retrieval_half_life_turns` · `retrieval_candidate_multiplier` ·  
`retrieval_weight_similarity` · `retrieval_weight_importance` · `retrieval_weight_time` ·
`retrieval_ancestor_weight` · `dedup_write_threshold` · `graph_min_importance` ·
`graph_max_relations` ·
`top_p` · `presence_penalty` · `frequency_penalty` · `repetition_penalty` · `reasoning_effort`

---

## API 参考

> 除公开静态头像 `/assets/avatars/*` 外，所有接口在 `.env` 中设置 `ACCESS_API_KEY` 后都需在请求头中携带 `X-API-Key: <your_key>`。
>
> 不再支持通过 `?api_key=` 或 `?token=` 传递长期密钥，避免密钥进入访问日志、浏览器历史或 Referer。
>
> 本地开发时留空 `ACCESS_API_KEY` 即可免鉴权。

### 静态资源认证约定

- **头像**：`/assets/avatars/{filename}` 是公开静态地址，图片组件可以直接访问，不需要认证请求头。接口中的 `avatar_path` 应为该公开资源的相对路径，或无需客户端长期密钥的短期签名绝对 URL；不得在头像 URL 中拼接长期 API Key。
- **音频**：后端返回 `/audio/{filename}` 相对 URL。该资源不是公开静态文件，客户端必须使用带 `X-API-Key` 请求头的下载请求获取临时文件后播放。
- **外部绝对 URL**：后端若返回外部绝对资源 URL，该 URL 必须本身公开或为短期签名地址，客户端不会向外部域名发送本后端的长期 API Key。

### 系统工具

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 服务健康检查 |
| POST | `/upload/avatar` | 上传头像（PNG/JPG/WEBP；大小上限由 `app.max_card_size_mb` 控制，当前为 10 MB） |
| GET | `/utils/settings` | 获取当前运行时配置 |
| PUT | `/utils/settings` | 热更新配置并持久化到 `config.yaml` |
| POST | `/utils/tts` | 文本转语音合成接口（返回合成音频的挂载 URL） |
| GET | `/audio/{filename}` | 使用 `X-API-Key` 请求头下载/播放音频（支持文件丢失后的在线延迟自愈重建） |

### 角色卡管理 `/characters`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/characters/parse` | 解析 PNG/JSON 角色卡，返回结构化数据（不入库） |
| POST | `/characters/create` | 将角色数据存入数据库 |
| GET | `/characters` | 获取所有角色简要列表 |
| GET | `/characters/{character_id}` | 获取角色完整设定 |
| GET | `/characters/{character_id}/memory-overview` | 分页获取故事记忆导航、最后消息和分支级统计 |
| PUT | `/characters/{character_id}` | 更新角色设定 |
| DELETE / POST | `/characters/{character_id}` 或 `/characters/{character_id}/delete` | 级联删除角色与所有会话，并通过 Outbox 异步清理 ChromaDB 集合、对话音频和不再被引用的受管头像（POST 用于兼容客户端） |

### 会话管理 `/sessions`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/sessions/create` | 新建会话（指定 `parent_session_id` 则继承分叉） |
| GET | `/sessions` | 分页查询角色会话，并可批量返回最后一条有效消息 |
| GET | `/sessions/{session_id}` | 获取会话详情（含 Persona 完整状态） |
| GET | `/sessions/{session_id}/history` | 获取会话聊天历史，支持 `limit` 与 `before_id` 游标分页 |
| PUT | `/sessions/{session_id}/title` | 修改会话标题 |
| DELETE / POST | `/sessions/{session_id}` 或 `/sessions/{session_id}/delete` | 安全删除会话，自动重连子节点继承链 (POST 用于避让) |
| POST | `/sessions/{session_id}/trigger_summary` | 手动触发记忆提纯 |
| POST | `/sessions/{session_id}/trigger_cognition` | 手动触发认知状态更新 |
| PUT | `/sessions/messages/{message_id}` | 编辑消息内容 |
| DELETE / POST | `/sessions/messages/{message_id}` 或 `/sessions/messages/{message_id}/delete` | 删除消息（自动回滚好感与情绪） |
| GET | `/sessions/{session_id}/memories` | 服务端筛选并分页返回当前故事的记忆、总数和分类统计 |
| POST | `/sessions/{session_id}/memories` | 手动写入当前会话的专属向量记忆 |
| PUT | `/sessions/{session_id}/memories/{memory_id}` | 修改当前会话的本地专属向量记忆（继承只读） |
| DELETE | `/sessions/{session_id}/memories/{memory_id}` | 删除当前会话的本地专属向量记忆（继承只读） |
| GET | `/sessions/{session_id}/compile_prompt` | 调试端点：预览/编译最近一次大模型 Prompt 组装 |

### 世界书管理 `/lorebooks`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/lorebooks/import` | 导入并解析 SillyTavern 格式的世界书 JSON 文件 |
| GET | `/lorebooks` | 查询系统中所有独立世界书列表 |
| GET | `/lorebooks/{lorebook_id}` | 获取单个世界书详情（包含所有条目） |
| PUT | `/lorebooks/{lorebook_id}` | 编辑更新世界书属性和条目 |
| DELETE / POST | `/lorebooks/{lorebook_id}` 或 `/lorebooks/{lorebook_id}/delete` | 删除指定世界书及其所有绑定关系 (POST 用于避让) |
| POST | `/lorebooks/characters/{character_id}/bind/{lorebook_id}` | 将指定世界书绑定到角色卡上 |
| POST | `/lorebooks/characters/{character_id}/unbind/{lorebook_id}` | 将指定世界书与角色卡解绑 |

### 对话核心 `/chat`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat` | 非流式对话（等待完整回复） |
| POST | `/chat/stream` | SSE 流式对话（逐 chunk 推送） |
| POST | `/chat/switch_candidate` | 设定当前活跃的消息候选版本（切换 active_index 并联动好感度） |

---

## 目录结构

```
app-backend/
├── main.py                  # 启动入口，路由注册，CORS
├── config.yaml              # 非敏感运行时配置
├── .env                     # 敏感密钥（不提交）
├── requirements.txt
├── query_db.py              # 数据库诊断工具
├── clear_db.py              # 数据库重置清理脚本
│
├── core/
│   ├── models.py            # SQLAlchemy ORM 模型定义
│   ├── database.py          # 数据库连接、Session 工厂与 Alembic 迁移执行函数（由 main.py startup 调用）
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
│   └── utils.py             # /upload/avatar 与 /utils/tts 端点
│
├── services/                # 业务服务层 (高内聚核心业务逻辑，分包管理)
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
│   │   └── session_memory_service.py # 会话专属记忆管理服务
│   ├── character_service.py # 角色卡增删改查业务服务
│   ├── parse.py             # SillyTavern 角色卡解析与清洗
│   └── tts_service.py       # TTS 文本预处理与音频缓存自愈重建服务
│
├── schemas.py               # Pydantic 请求/响应模型
├── alembic.ini              # Alembic 数据库迁移配置文件
├── alembic/                 # Alembic 数据库迁移版本控制目录
│
├── tests/                   # 系统单元测试与集成测试套件目录
│   ├── test_config.py       # 动态配置参数加载单元测试
│   ├── test_alembic_cli.py  # Alembic CLI 直接执行与递归导入回归测试
│   ├── test_delete_candidate.py # 消息候选版本删除好感度回滚单元测试
│   ├── test_independent_lorebook.py # 独立世界书绑定与扫描单元测试
│   ├── test_lorebook.py     # 世界书引擎匹配与预算裁剪单元测试
│   ├── test_lorebook_trigger_compatibility.py # 世界书过滤逻辑、正则与概率兼容测试
│   ├── test_memory_deduplication.py # 记忆替代与多级继承集成测试
│   ├── test_branching_start_message.py # 剧情线分叉首条消息克隆绑定测试
│   ├── test_branch_context_boundary.py # 分叉点持久化与父分支未来消息隔离测试
│   ├── test_memory_handoff.py # 短期上下文与长期记忆动态交接测试
│   ├── test_contextual_retrieval_query.py # 上下文化检索、边界与预算测试
│   ├── test_memory_card_extraction.py # 完整记忆卡、来源范围与失败回滚测试
│   ├── test_memory_versioning.py # same/replace/coexist、分支局部替代与否定词回归测试
│   ├── manual_deepseek_memory_quality.py # 仅调用聊天模型的人工提纯质量样例
│   ├── test_memory_manager_offline.py # 向量故障降级与已知缺陷诊断测试
│   ├── test_graph_rag.py    # 知识图谱 Graph RAG 增强检索测试
│   ├── test_graph_rag_quality.py # 别名、分支覆盖、真实 2-hop 与枢纽抑制离线测试
│   ├── test_outbox.py       # 发件箱模式任务消费与退避重试单元测试
│   ├── test_avatar_cleanup.py # 受管头像删除、共享引用、越界防护与幂等清理测试
│   ├── test_parse.py        # SillyTavern V1/V2 角色卡解析与清洗单元测试
│   ├── test_character_prompt_compatibility.py # Prompt DSL、Depth Prompt、单卡多逻辑角色与 Main RP Prompt 兼容测试
│   ├── test_tts_api.py      # TTS 预处理过滤及云端合成测试
│   ├── test_closed_loop_memory.py # 记忆提纯与 RAG 闭环流程测试
│   └── test_api.py          # 路由树与会话剧情重连集成测试
│
└── data/
    ├── data.db              # SQLite 关系型数据库文件 (WAL 模式)
    ├── chroma_data/         # ChromaDB 向量文件夹
    └── audio_cache/         # 合成音频文件本地缓存目录 (.mp3)
```

---

## 测试

所有单元测试和集成测试均存放于 `tests/` 目录下，在运行测试前请确保已激活虚拟环境。

Windows 开发环境可以直接使用项目虚拟环境解释器运行完全离线测试（不依赖外部大模型及向量数据库）：

```powershell
.\venv\Scripts\python.exe .\tests\test_branch_context_boundary.py      # 分叉边界持久化与未来消息隔离测试
.\venv\Scripts\python.exe .\tests\test_memory_handoff.py              # 短短期上下文与长期记忆动态交接测试
.\venv\Scripts\python.exe .\tests\test_contextual_retrieval_query.py   # 上下文化检索查询生成与边界测试
.\venv\Scripts\python.exe .\tests\test_memory_card_extraction.py       # 语义记忆卡提取及来源定位测试
.\venv\Scripts\python.exe .\tests\test_memory_versioning.py            # same/replace/coexist 分支局部替代关系测试
.\venv\Scripts\python.exe .\tests\test_memory_manager_offline.py       # 向量数据库不可用时降级退避与冷处理测试
.\venv\Scripts\python.exe -m unittest tests.test_vector_outbox_consistency -v # SQLite-Chroma 一致性测试
.\venv\Scripts\python.exe -m unittest tests.test_alembic_cli -v        # Alembic 启动与命令行冲突避免测试
.\venv\Scripts\python.exe .\tests\test_prompt_token_estimator.py       # 启发式 Token 估算器与块分析测试
.\venv\Scripts\python.exe .\tests\test_character_prompt_compatibility.py # 角色卡 Prompt DSL 与 Main RP Prompt 兼容测试
.\venv\Scripts\python.exe -m unittest tests.test_avatar_cleanup -v       # 受管头像生命周期与安全删除测试
.\venv\Scripts\python.exe -m unittest discover -s tests -p 'test_lorebook_trigger_compatibility.py' -v # 世界书触发语义兼容测试
.\venv\Scripts\python.exe .\tests\test_router_service_boundaries.py    # 路由层参数与异常处理的边界单元测试
```

这些测试不会调用真实对话模型或向量模型，提供稳定的离线持续回归验证。

如果运行全套集成与单元测试，请在终端（激活环境后）执行对应的脚本：

```bash
# 1. 动态配置参数加载与热更新单元测试
python tests/test_config.py

# 2. 消息候选版本（Swipe）切换与删除好感度/心情回滚测试
python tests/test_delete_candidate.py

# 3. 独立世界书（Lorebook）加载与角色绑定测试
python tests/test_independent_lorebook.py

# 4. 世界书关键词匹配、深度扫描与 Token 限制裁剪测试
python tests/test_lorebook.py

# 5. 记忆合并替代与跨分支继承的图谱/向量召回集成测试
python tests/test_memory_deduplication.py

# 6. 分剧情线分叉起点克隆绑定首条消息测试
python tests/test_branching_start_message.py

# 7. 知识图谱 Graph RAG 两邻接点召回与合并重叠实体测试
python tests/test_graph_rag.py

# 8. 知识图谱图论相关特性（别名处理、COW 关系折叠、枢纽抑制）测试
python tests/test_graph_rag_quality.py

# 9. 发件箱 outbox_worker 异常断电租约锁与指数退避重试测试
python tests/test_outbox.py

# 10. SillyTavern V1/V2 角色卡解析、元数据解码与 HTML 清洗测试
python tests/test_parse.py

# 11. TTS 前处理（动作过滤、声效保留）及云端合成模拟测试
python tests/test_tts_api.py

# 12. 记忆提纯触发、认知更新迭代与 RAG 结合的闭环流程测试
python tests/test_closed_loop_memory.py

# 13. 对话流式接口中途异常、断开导致的消息事务性物理回滚与释放锁测试
python tests/test_chat_turn_service.py

# 14. 向量嵌入失败下的容错和空值响应退避策略测试
python tests/test_embedding_failure_policy.py

# 15. 路由树挂载、级联删除重连与会话继承树完整性集成测试
python tests/test_api.py
```

需要人工抽查真实大模型对于记忆提取身份解析、卡片颗粒度生成的质量时，可运行：

```powershell
.\venv\Scripts\python.exe .\tests\manual_deepseek_memory_quality.py
```

该脚本调用配置中的记忆提取大模型，但会使用内存 Mock 屏蔽向量与图谱写入，因此不依赖真实 ChromaDB 服务。

Alembic 迁移机制与命令行也受到完全支持。加载 `alembic/env.py` 时会自动识别命令行环境并临时屏蔽 `database.py` 的应用级自动升级副作用，确保无循环：

```powershell
.\venv\Scripts\python.exe -m alembic heads
.\venv\Scripts\python.exe -m alembic current
.\venv\Scripts\python.exe -m alembic upgrade head
```

---

## 注意事项

- **单用户私有部署限制**：本项目为单用户私有部署设计，未隔离多租户的数据库与 ChromaDB 集合。如果在公网或多端部署，请务必在 `.env` 中指定 `ACCESS_API_KEY` 以保护接口安全。
- **密钥传输边界**：长期 `ACCESS_API_KEY` 只允许放在 `X-API-Key` 请求头中，禁止拼接到头像、音频或其他 URL。生产环境还必须启用 HTTPS，避免请求头在传输途中被窃听。
- **自愈缓存策略**：本地音频缓存目录（`data/audio_cache/`）可以根据需要进行手动清理或重命名。系统带有自愈模式，如果物理文件丢失但数据库有路径，它会在用户下一次触发朗读时默默发起被动重建，完全不影响系统运行。
- **历史分页性能**：通过 `/sessions/{id}/history` 查询历史记录时，参数 `before_id` 可作为分页游标，强烈建议前端在聊天页初始化时分步拉取（如每次获取 50 条），并在滚动触顶时按需往前拉取，避免长会话引起的内存暴涨。
- **移动端与 Nginx 兼容（DELETE 降级避让）**：为防范移动原生客户端及 Nginx 反向代理层在 HTTP 强跳转 HTTPS 时自动将 `DELETE` 重定向并降级为 `GET` 的现象，所有的物理删除接口均已挂载 `DELETE` 和 `POST .../delete` 双通道路径。移动端开发或联调时推荐统一走 `POST .../delete` 通道。
