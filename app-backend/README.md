# AI Roleplay Backend Engine

> 基于 FastAPI + SQLite + ChromaDB 构建的个人私有部署 AI 角色扮演后端。  
> 支持高精度角色模拟、长期记忆 RAG 检索、分支树状会话、认知与好感度闭环演化、多模态语音合成（TTS）以及多分支候选回复机制。

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
| 语音合成 | Cloud MIMO-v2.5-tts | 高质感角色配音合成与人声效果渲染 |
| LLM 接入 | OpenAI-compatible API | 对话生成、记忆提纯、认知更新、TTS 文本前处理 |
| 高速匹配 | Aho-Corasick 自动机 | 世界书（Lorebook）关键词触发 |

---

## 核心特性

### 1. Prompt Caching 友好的提示词引擎

- **静态 / 动态内容彻底分离**：角色设定、性格描述、输出格式规范等纯静态内容归入 `system_prompt`，最大化命中主流 API 的 Prompt Cache。
- **XML 上下文闭包注入**：当前场景、认知状态、好感心情、世界书条目、RAG 召回记忆等动态内容统一以 XML 标签包裹，追加到当轮 `user` 消息末尾。
- **严格的角色交替序列**：`system → user/assistant → user`，完美兼容 Claude、Gemini、DeepSeek 等对 alternating roles 有强约束的 API。

### 2. 多分支候选回复机制 (Swipe Multi-Replies)

- **多版本生成**：同一轮对话支持生成和存储多个 AI 候选回复版本（Candidates）。
- **活动版本切换**：通过 `/chat/switch_candidate` 接口，可自由设定某一条候选回复为活动状态（`is_active=True`），同时将其兄弟回复置为 `is_active=False`。
- **元数据绑定**：每个候选回复版本在数据库中独立绑定其情绪标签（`emotion_tag`）、好感度变动（`affection_change`）以及生成的音频路径（`audio_path`）。切换候选回复时，好感度和情绪指标会自动联动回滚并重算，实现“音画同步、多版本安全切换”。

### 3. 多模态语音合成（TTS）与自愈式 LRU 缓存管道

- **人声情感与拟真事件支持**：接入云端 MIMO-v2.5-tts API，原生支持“开心、悲伤、愤怒、温柔、悄悄话、唱歌”等 6 种情感配音，以及“（叹气）、（笑声）、（哭声）、（咳嗽）、[inhale]（深呼吸/吸气）”等拟真声音事件。
- **智能文本前处理（双预处理器）**：
  - **LLM 预处理器**：使用非推理快速模型（如 `deepseek-v4-flash`）对角色发言进行预处理，**100% 剥离**非发音的物理动作、心理活动、场景叙述和对话前缀（如“她微微一笑说道：”），仅提取并保留实际发音的台词。
  - **声音标记保护机制**：在过滤前对声效标记进行占位符暂存保护，过滤完毕后还原，确保合成的声音富有人声细节而不“机械读动作”。
  - **正则规则预处理器**：在 LLM API 故障时提供自动回退，确保系统高可用。
- **自愈式 LRU 缓存系统**：
  - 生成的文件缓存于本地（`data/audio_cache`）。
  - **物理丢失自愈**：当播放请求到达时，系统检测到数据库中存在 `audio_path` 但本地物理文件丢失（例如用户清理了缓存或被 LRU 线程淘汰），会**自动触发被动重建**重新合成，保障播放永不中断。
  - **后台 LRU 清理**：由守护线程 `_prune_cache_background` 监控缓存文件总数，超限时根据最后修改时间自动淘汰老音频。
- **音频静态托管**：后端在启动时会自动建立并挂载 `/audio` 静态服务，前端可直接通过 URL 进行流式音频播放，规避多端平台（App/微信小程序）内置 SVG 组件可能带来的兼容性报错。

### 4. 数据库零手工免配置动态升级

- **启动期自适应升级**：系统启动导入 `core/database.py` 时，会自动利用 `inspect` 工具扫描现有的 SQLite 数据库。
- **动态 Alter Column**：检测到旧数据库缺少 `audio_path`、`parent_id` 或 `is_active` 字段时，会自动运行 SQL 指令进行在轨升级（如 `ALTER TABLE chat_messages ADD COLUMN audio_path VARCHAR(255) NULL`），彻底消除数据库结构变更导致的崩溃。

### 5. 游标滚动分页历史消息 API

- 会话历史查询接口 `/sessions/{id}/history` 升级支持 `limit`（数量限制）与 `before_id`（游标 ID）参数。
- 前端可按需分段向前分页加载 50 条消息，规避了一次性加载上百条消息导致移动客户端渲染卡顿、Token 溢出的性能瓶颈，提供更流畅的滚动体验。

### 6. 会话级异步并发锁

- 使用 `asyncio.Lock` 实现单会话串行保证，完全在事件循环层挂起，零线程资源占用。
- 非流式端点：`try/finally` 保证锁必然释放。
- 流式端点：锁的生命周期绑定到 SSE `StreamingResponse` 生成器的 `finally` 块，彻底防止多客户端竞态导致的写乱序。
- 会话删除时自动从锁字典中清理对应条目，防止长期运行内存增长。

### 7. 长期记忆 RAG 检索管道

- 每个角色拥有专属 ChromaDB Collection，按 Persona 隔离存储。
- 进阶祖先链检索：使用单次 SQLite CTE 递归查询，规避 RAG 时出现多轮 N+1 查询。
- **三维混合打分精排**：**余弦相似度（60%）+ 内容重要性（20%）+ 时间衰减（20%）**，对父辈及祖先会话条目额外施加代际惩罚权重。
- **图谱关联召回**：与 **Graph RAG** 关系提取相匹配，召回时混合查询数据库事实三元组，获得更精准的事实一致性上下文。
- 所有权重、半衰期、候选倍数均可在 `config.yaml` 中调整，无需重启即可通过 API 热更新。

### 8. 会话继承树（分叉剧情线）

- 支持从任意历史会话或指定消息节点 fork 出子会话，继承好感度、认知状态、当前场景与心情。
- **分支起始消息自动绑定**：创建分支时，系统会自动复制触发分叉的该条源消息（若未指定则退避到父会话的最后一条激活消息）克隆一份绑定到新分支会话的开头，防止新分支页面呈现空白，并保持故事流畅衔接。
- 删除中间节点时自动将子节点重连到父节点，继承链不断裂。
- RAG 检索跨代际透明合并，代数越远权重越低。

### 9. 认知与好感度闭环

- **记忆提纯**：对话满足条数阈值后自动触发，LLM 提炼近期对话为结构化记忆条目，写入 SQLite + ChromaDB 双存储。
- **认知更新**：基于高重要性记忆定期更新角色的自我认知状态文本（`cognition_state`）。
- **好感度回滚**：删除 assistant 消息时自动逆向回滚好感值与心情状态。

### 10. 零依赖 SillyTavern Card V2 解析器

- 支持 PNG（`tEXt` / `zTXt` / `iTXt`）和 JSON 格式，无需第三方图像库。
- 兼容 V1 / V2 规范及各平台变种字段。
- 入库时自动将角色卡内的 HTML 标签清洗为 Markdown，降低 Token 消耗并防止注入。

### 11. 独立世界书与 SillyTavern 兼容引擎 (Independent Lorebook)

- **多数据源载入**：支持为角色独立绑定、加载外部世界书（Lorebooks），或直接使用角色卡自带的设定。
- **SillyTavern 兼容性**：完美解析与支持 SillyTavern 格式的世界书 JSON，支持关键词权重、常量激活、递归扫描等策略。
- **高性能关键词匹配**：利用 **Aho-Corasick（AC自动机）** 算法，在单轮会话中对全部文本和所有世界书关键词进行高效的单次扫描，极大地规避了多关键词下遍历匹配的性能开销。
- **递归扫描与 Token 预算**：支持深度定制的 `scan_depth` 和 `token_budget` 上限，自适应调整载入的世界书条目，防止上下文 Token 溢出。

### 12. 知识图谱双向增强检索 (Graph RAG)

- **实体与关系提取**：记忆提纯时除了沉淀向量文本记忆，还会自动提取实体（Entity）与关系（Relation）三元组写入 SQLite 图关系网络。
- **混合增强 RAG**：在对话检索时，不仅进行向量数据库（ChromaDB）语义匹配，还会自动联想并召回相关的图谱实体与二阶事实关系（如“A是B的妹妹，B喜欢C”），弥补了传统向量检索在长路径事实关联与多跳推理上的短板。
- **异常容错与回滚**：若大模型输出非法格式，自动捕获并保留上一轮指针重试，写入异常时触发 SQLite 事务回滚与已写向量同步清理，保证数据库零脏数据。

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
  reasoning_effort: null

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
`dedup_write_threshold` · `dedup_retrieve_text_threshold` · `graph_min_importance` · `graph_max_relations`

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
| GET | `/characters/{id}` | 获取角色完整设定 |
| PUT | `/characters/{id}` | 更新角色设定 |
| DELETE / POST | `/characters/{id}` 或 `/characters/{id}/delete` | 级联删除角色、所有会话及 ChromaDB 集合 (POST 用于避让) |

### 会话管理 `/sessions`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/sessions/create` | 新建会话（指定 `parent_session_id` 则继承分叉） |
| GET | `/sessions` | 查询角色的所有会话列表 |
| GET | `/sessions/{id}` | 获取会话详情（含 Persona 完整状态） |
| GET | `/sessions/{id}/history` | 获取会话聊天历史，支持 `limit` 与 `before_id` 游标分页 |
| PUT | `/sessions/{id}/title` | 修改会话标题 |
| DELETE / POST | `/sessions/{id}` 或 `/sessions/{id}/delete` | 安全删除会话，自动重连子节点继承链 (POST 用于避让) |
| POST | `/sessions/{id}/trigger_summary` | 手动触发记忆提纯 |
| POST | `/sessions/{id}/trigger_cognition` | 手动触发认知状态更新 |
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
├── routers/
│   ├── chat.py              # /chat 与 /chat/stream 及 /chat/switch_candidate
│   ├── sessions.py          # /sessions 端点（分页历史、消息/记忆管理、调试等）
│   ├── characters.py        # /characters 端点
│   ├── lorebooks.py         # /lorebooks 端点（导入、详情、编辑、绑定等）
│   └── utils.py             # /upload/avatar 与 /utils/tts 端点
│
├── services/
│   ├── chat_engine.py       # LLM 调用、Prompt 组装、流式封装
│   ├── tts_service.py       # TTS 前处理（动作过滤、声效保留）、云端合成、LRU 音频缓存
│   ├── memory_manager.py    # RAG 检索、记忆存储、外观层入口
│   ├── cognition_service.py # 记忆提纯、认知更新
│   ├── lorebook_engine.py   # 世界书关键词匹配与注入
│   ├── ahocorasick.py       # Aho-Corasick 自动机实现
│   ├── session_service.py   # 会话删除与继承链重连
│   └── parse.py             # SillyTavern 角色卡解析
│
├── schemas.py               # Pydantic 请求/响应模型
└── data/
    ├── data.db              # SQLite 数据库文件
    ├── chroma_data/         # ChromaDB 向量文件夹
    └── audio_cache/         # 合成音频缓存目录（.wav）
```

---

## 测试

```bash
# 语音合成接口（TTS 预处理、动作过滤与声效保留）单元测试
python test_tts_api.py

# 世界书独立触发单元测试
python test_lorebook.py

# 记忆提纯与 RAG 闭环集成测试
python test_closed_loop_memory.py

# 会话树重连与 API 路由测试
python test_api.py
```

---

## 注意事项

- **单用户私有部署限制**：本项目为单用户私有部署设计，未隔离多租户的数据库与 ChromaDB 集合。如果在公网或多端部署，请务必在 `.env` 中指定 `ACCESS_API_KEY` 以保护接口安全。
- **自愈缓存策略**：本地音频缓存目录（`data/audio_cache/`）可以根据需要进行手动清理或重命名。系统带有自愈模式，如果物理文件丢失但数据库有路径，它会在用户下一次触发朗读时默默发起被动重建，完全不影响系统运行。
- **历史分页性能**：通过 `/sessions/{id}/history` 查询历史记录时，参数 `before_id` 可作为分页游标，强烈建议前端在聊天页初始化时分步拉取（如每次获取 50 条），并在滚动触顶时按需往前拉取，避免长会话引起的内存暴涨。
- **移动端与 Nginx 兼容（DELETE 降级避让）**：为防范移动原生客户端及 Nginx 反向代理层在 HTTP 强跳转 HTTPS 时自动将 `DELETE` 重定向并降级为 `GET` 的现象，所有的物理删除接口均已挂载 `DELETE` 和 `POST .../delete` 双通道路径。移动端开发或联调时推荐统一走 `POST .../delete` 通道。
