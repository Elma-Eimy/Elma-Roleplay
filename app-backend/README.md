# AI Roleplay Backend Engine

> 基于 FastAPI + SQLite + ChromaDB 构建的私有化部署 AI 角色扮演后端服务。  
> 支持角色深度模拟、长期记忆 RAG 检索、树状分支会话管理、认知与好感度动态演化、多模态 TTS 音频生成以及多候选回复分支机制。

---

## 目录

- [技术栈](#技术栈)
- [核心特性](#核心特性)
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

- **静态与动态内容分离**：将角色设定、性格描述、规范等静态内容归入 `system_prompt`，以利于命中断点 API 的 Prompt Cache。
- **XML 上下文闭包注入**：当前场景、认知状态、好感心情、世界书条目、RAG 召回记忆等动态内容统一以 XML 标签包裹，追加到当轮 `user` 消息末尾。
- **严格的角色交替序列**：使用 `system → user/assistant → user` 结构，兼容 Claude、Gemini、DeepSeek 等对 alternating roles 有强约束的 API。

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
- **音频托管**：挂载 `/audio` 静态服务，前端可通过 URL 播放，规避跨端组件兼容性问题。

### 4. 数据库自动迁移升级与 Alembic 机制

- **启动期自适应升级**：系统启动导入 `core/database.py` 时，会自动使用 Alembic 扫描并自动应用所有新迁移升级（通过 `command.upgrade` 直达 `head` 版本）。
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
- 所有权重、半衰期、候选倍数均可在 `config.yaml` 中调整，无需重启即可通过 API 热更新。

### 8. 会话继承树（分叉剧情线）

- 支持从任意历史会话或指定消息节点 fork 出子会话，继承好感度、认知状态、当前场景与心情。
- **分支起始消息自动绑定**：创建分支时，系统会自动复制触发分叉的该条源消息（若未指定则退避到父会话的最后一条激活消息）克隆一份绑定到新分支会话的开头，避免新分支页面呈现空白。
- 删除中间节点时自动将子会话重连到父会话，保持继承链完整。
- RAG 检索支持跨代会话合并，权重随代数增加而衰减。

### 9. 认知与好感度闭环

- **记忆提纯**：对话满足条数阈值后自动触发，LLM 提炼近期对话为结构化记忆条目，写入 SQLite + ChromaDB 双存储。
- **认知更新**：基于高重要性记忆定期更新角色的自我认知状态文本（`cognition_state`）。
- **好感度回滚**：删除 assistant 消息时自动逆向回滚好感值与心情状态。

### 10. SillyTavern Card V2 解析

- 支持 PNG（`tEXt` / `zTXt` / `iTXt`）和 JSON 格式，无需第三方图像库。
- 兼容 V1 / V2 规范及各平台变种字段。
- 入库时自动将角色卡内的 HTML 标签清洗为 Markdown，降低 Token 消耗并防止注入。

### 11. 独立世界书与 SillyTavern 格式兼容 (Independent Lorebook)

- **多数据源载入**：支持为角色独立绑定、加载外部世界书（Lorebooks），或直接使用角色卡自带的设定。
- **SillyTavern 兼容性**：支持解析 SillyTavern 格式的世界书 JSON，支持关键词权重、常量激活、递归扫描等策略。
- **关键词匹配**：利用 **Aho-Corasick（AC自动机）** 算法，在单轮会话中对文本和世界书关键词进行扫描，降低多关键词下的遍历匹配开销。
- **递归扫描与 Token 预算**：支持定制 `scan_depth` 和 `token_budget` 上限，自适应调整载入的世界书条目，防止上下文 Token 溢出。

### 12. 知识图谱双向增强检索 (Graph RAG)

- **实体与关系提取**：记忆提纯时除了沉淀向量文本记忆，还会自动提取实体（Entity）与关系（Relation）三元组写入 SQLite 图关系网络。
- **混合增强 RAG**：在对话检索时，结合向量数据库（ChromaDB）语义匹配与图谱实体关系召回，辅助传统向量检索在长路径关联与推理上的表现。
- **异常容错与回滚**：若大模型输出非法格式，自动捕获重试；写入异常时触发 SQLite 事务回滚与向量清理，保持数据一致性。

### 13. 对话回合事务原子性 (Dialogue State Atomicity)

- **故障自动回滚**：为了避免 SQLite 的写锁定，用户消息先提交入库再触发大模型调用。若之后的 Prompt 装配、大模型 API 调用、SSE 流式解析或回复结果保存发生任何异常，系统会自动在后台触发消息回滚，物理删除该条未作答的用户消息，确保数据库状态的一致性，防止历史对话中留有未回复的用户残留消息。
- **流式对话自愈**：在 `/chat/stream` 生成期间出现异常或前端中断时，该机制同样生效，能同步清理残余状态并释放会话级异步锁。

### 14. 统一大模型适配器层 (Unified LLM Provider)

- **完全解耦解包**：将核心服务（如 `cognition_service` 与 `tts_service`）的第三方 SDK（如直接调用 OpenAI 库）全部解耦，移入适配器层。
- **动态统一调用**：所有对话生成、记忆提炼、情感风格分析均通过 `services/llm_provider.py` 的 `generate` 与 `generate_async` 进行统一封装和动态转发，方便轻松替换底层模型供应商。

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
  memory_extract_history_limit: 20             # 记忆提纯扫描的历史条数上限
  retrieval_min_importance: 0.3                # 记忆重要性过滤阈值（0~1）
  retrieval_max_distance: 1.2                  # 向量余弦距离过滤上限
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
  dedup_write_threshold: 0.15                  # 写时去重向量距离门槛（小于此值触发 LLM 合并）
  dedup_retrieve_text_threshold: 0.70          # 检索侧去重文本相似度比例门槛（SequenceMatcher）
  graph_min_importance: 0.5                    # 图谱检索关系过滤最低重要性
  graph_max_relations: 12                      # 图谱检索单次最大装填关系数量

  # 存储路径
  sqlite_db_path: data/data.db
  chroma_db_path: data/chroma_data
  upload_avatar_dir: ./assets/avatars

  # 安全与限制
  cors_origins:
    - "*"                                      # 生产环境建议改为具体域名
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
`retrieval_top_k` · `retrieval_min_importance` · `retrieval_max_distance` ·  
`lorebook_scan_depth` · `lorebook_token_budget` · `lorebook_max_recursive_passes` ·  
`cognition_max_words` · `retrieval_half_life_turns` · `retrieval_candidate_multiplier` ·  
`top_p` · `presence_penalty` · `frequency_penalty` · `repetition_penalty` · `reasoning_effort`

---

## API 参考

> 所有接口在 `.env` 中设置 `ACCESS_API_KEY` 后需在 Header 中携带 `X-API-Key: <your_key>`。  
> 本地开发时留空 `ACCESS_API_KEY` 即可免鉴权。

### 系统工具

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/` | 服务健康检查 |
| POST | `/upload/avatar` | 上传头像（PNG/JPG/WEBP，≤5MB） |
| GET | `/utils/settings` | 获取当前运行时配置 |
| PUT | `/utils/settings` | 热更新配置并持久化到 `config.yaml` |
| POST | `/utils/tts` | 文本转语音合成接口（返回合成音频的挂载 URL） |

### 角色卡管理 `/characters`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/characters/parse` | 解析 PNG/JSON 角色卡，返回结构化数据（不入库） |
| POST | `/characters/create` | 将角色数据存入数据库 |
| GET | `/characters` | 获取所有角色简要列表 |
| GET | `/characters/{character_id}` | 获取角色完整设定 |
| PUT | `/characters/{character_id}` | 更新角色设定 |
| DELETE / POST | `/characters/{character_id}` 或 `/characters/{character_id}/delete` | 级联删除角色、所有会话及 ChromaDB 集合 (POST 用于避让) |

### 会话管理 `/sessions`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/sessions/create` | 新建会话（指定 `parent_session_id` 则继承分叉） |
| GET | `/sessions` | 查询角色的所有会话列表 |
| GET | `/sessions/{session_id}` | 获取会话详情（含 Persona 完整状态） |
| GET | `/sessions/{session_id}/history` | 获取会话聊天历史，支持 `limit` 与 `before_id` 游标分页 |
| PUT | `/sessions/{session_id}/title` | 修改会话标题 |
| DELETE / POST | `/sessions/{session_id}` 或 `/sessions/{session_id}/delete` | 安全删除会话，自动重连子节点继承链 (POST 用于避让) |
| POST | `/sessions/{session_id}/trigger_summary` | 手动触发记忆提纯 |
| POST | `/sessions/{session_id}/trigger_cognition` | 手动触发认知状态更新 |
| PUT | `/sessions/messages/{message_id}` | 编辑消息内容 |
| DELETE / POST | `/sessions/messages/{message_id}` 或 `/sessions/messages/{message_id}/delete` | 删除消息（自动回滚好感与情绪） |
| GET | `/sessions/{session_id}/memories` | 获取当前会话的可用向量记忆列表（含继承，支持检索与分页） |
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
│   ├── database.py          # 数据库连接、Session 工厂与自适应在轨迁移逻辑
│   ├── config.py            # Settings 类，加载 .env + config.yaml
│   ├── auth.py              # X-API-Key 鉴权依赖
│   ├── locking.py           # 会话级 asyncio.Lock 管理
│   └── utils.py             # 工具函数（获取本机 IP 等）
│
├── routers/                 # 路由层 (轻量级，仅负责 HTTP 路径定义、参数校验与异常封装，具体业务委托给 services)
│   ├── chat.py              # /chat 与 /chat/stream 及 /chat/switch_candidate
│   ├── sessions.py          # /sessions 端点（分页历史、消息/记忆管理、调试等）
│   ├── characters.py        # /characters 端点
│   ├── lorebooks.py         # /lorebooks 端点（导入、详情、编辑、绑定等）
│   └── utils.py             # /upload/avatar 与 /utils/tts 端点
│
├── services/                # 业务服务层 (高内聚核心业务逻辑，脱离 HTTP 协议)
│   ├── chat_engine.py       # LLM 执行引擎 (专注于大模型请求参数合并与响应结构化解析)
│   ├── context_assembler.py # 对话上下文装配服务 (统一装配 RAG 检索、知识图谱与对话历史，拼装 Prompt)
│   ├── llm_provider.py      # 大模型服务适配器 (抽象适配层，解耦具体大模型厂商 API SDK)
│   ├── tts_service.py       # TTS 前处理（动作过滤、声效保留）、云端合成、LRU 音频缓存
│   ├── memory_manager.py    # RAG 检索、记忆存储、外观层入口
│   ├── cognition_service.py # 记忆提纯、认知更新
│   ├── lorebook_engine.py   # 世界书关键词匹配与注入
│   ├── ahocorasick.py       # Aho-Corasick 自动机实现
│   ├── session_service.py   # 会话生命周期、分支拷贝、消息删除状态回滚业务服务
│   └── parse.py             # SillyTavern 角色卡解析
│
├── schemas.py               # Pydantic 请求/响应模型
├── alembic.ini              # Alembic 数据库迁移配置文件
├── alembic/                 # Alembic 数据库迁移版本控制目录
│
├── tests/                   # 系统单元测试与集成测试套件目录
│   ├── test_config.py       # 动态配置参数加载单元测试
│   ├── test_delete_candidate.py # 消息候选版本删除好感度回滚单元测试
│   ├── test_independent_lorebook.py # 独立世界书绑定与扫描单元测试
│   ├── test_lorebook.py     # 世界书引擎匹配与预算裁剪单元测试
│   ├── test_memory_deduplication.py # 继承链去重新增与写时复制 (COW) 单元测试
│   ├── test_branching_start_message.py # 剧情线分叉首条消息克隆绑定测试
│   ├── test_graph_rag.py    # 知识图谱 Graph RAG 增强检索测试
│   ├── test_outbox.py       # 发件箱模式任务消费与退避重试单元测试
│   ├── test_parse.py        # SillyTavern V1/V2 角色卡解析与清洗单元测试
│   ├── test_tts_api.py      # TTS 预处理过滤及云端合成测试
│   ├── test_closed_loop_memory.py # 记忆提纯与 RAG 闭环流程测试
│   └── test_api.py          # 路由树与会话剧情重连集成测试
│
└── data/
    ├── data.db              # SQLite 关系型数据库文件 (WAL 模式)
    ├── chroma_data/         # ChromaDB 向量文件夹
    └── audio_cache/         # 合成音频文件本地缓存目录 (.wav)
```

---

## 测试

所有单元测试和集成测试均存放于 `tests/` 目录下，在运行测试前请确保已激活虚拟环境。

```bash
# 1. 动态配置参数加载单元测试
python tests/test_config.py

# 2. 消息候选版本删除与好感度回滚单元测试
python tests/test_delete_candidate.py

# 3. 独立世界书绑定与匹配注入单元测试
python tests/test_independent_lorebook.py

# 4. 世界书引擎检索与条件触发单元测试
python tests/test_lorebook.py

# 5. 记忆合并去重与写时复制 (COW) 继承单元测试
python tests/test_memory_deduplication.py

# 6. 分叉剧情线分支起始消息复制与自动绑定测试
python tests/test_branching_start_message.py

# 7. 知识图谱 Graph RAG 双向检索增强集成测试
python tests/test_graph_rag.py

# 8. 发件箱异步任务重试与退避调度测试
python tests/test_outbox.py

# 9. SillyTavern 角色卡解析与清洗单元测试
python tests/test_parse.py

# 10. 语音合成预处理（动作过滤、声效保留）单元测试
python tests/test_tts_api.py

# 11. 记忆提纯与 RAG 闭环集成测试
python tests/test_closed_loop_memory.py

# 12. 会话剧情线重连、继承与 API 路由测试
python tests/test_api.py
```

---

## 注意事项

- **单用户私有部署限制**：本项目为单用户私有部署设计，未隔离多租户的数据库与 ChromaDB 集合。如果在公网或多端部署，请务必在 `.env` 中指定 `ACCESS_API_KEY` 以保护接口安全。
- **自愈缓存策略**：本地音频缓存目录（`data/audio_cache/`）可以根据需要进行手动清理或重命名。系统带有自愈模式，如果物理文件丢失但数据库有路径，它会在用户下一次触发朗读时默默发起被动重建，完全不影响系统运行。
- **历史分页性能**：通过 `/sessions/{id}/history` 查询历史记录时，参数 `before_id` 可作为分页游标，强烈建议前端在聊天页初始化时分步拉取（如每次获取 50 条），并在滚动触顶时按需往前拉取，避免长会话引起的内存暴涨。
- **移动端与 Nginx 兼容（DELETE 降级避让）**：为防范移动原生客户端及 Nginx 反向代理层在 HTTP 强跳转 HTTPS 时自动将 `DELETE` 重定向并降级为 `GET` 的现象，所有的物理删除接口均已挂载 `DELETE` 和 `POST .../delete` 双通道路径。移动端开发或联调时推荐统一走 `POST .../delete` 通道。
