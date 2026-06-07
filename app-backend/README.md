# AI Roleplay Backend Engine

> 基于 FastAPI + SQLite + ChromaDB 构建的个人私有部署 AI 角色扮演后端。  
> 支持高精度角色模拟、长期记忆 RAG 检索、分支树状会话、认知与好感度闭环演化。

---

## 目录

- [技术栈](#技术栈)
- [核心特性](#核心特性)
- [快速开始](#快速开始)
- [配置说明](#配置说明)
- [API 参考](#api-参考)
- [目录结构](#目录结构)
- [测试](#测试)

---

## 技术栈

| 层级 | 技术 | 作用 |
|------|------|------|
| 网络框架 | FastAPI + Uvicorn | 异步 HTTP / SSE 流式接口 |
| 关系型存储 | SQLAlchemy + SQLite (WAL) | 会话、消息、角色卡、Persona 状态 |
| 向量数据库 | ChromaDB | 长期记忆嵌入存储与相似度检索 |
| LLM 接入 | OpenAI-compatible API | 对话生成、记忆提纯、认知更新 |
| 高速匹配 | Aho-Corasick 自动机 | 世界书（Lorebook）关键词触发 |

---

## 核心特性

### 1. Prompt Caching 友好的提示词引擎

- **静态 / 动态内容彻底分离**：角色设定、性格描述、输出格式规范等纯静态内容归入 `system_prompt`，最大化命中主流 API 的 Prompt Cache。
- **XML 上下文闭包注入**：当前场景、认知状态、好感心情、世界书条目、RAG 召回记忆等动态内容统一以 XML 标签包裹，追加到当轮 `user` 消息末尾。
- **严格的角色交替序列**：`system → user/assistant → user`，完美兼容 Claude、Gemini、DeepSeek 等对 alternating roles 有强约束的 API。

### 2. 会话级异步并发锁

- 使用 `asyncio.Lock` 实现单会话串行保证，完全在事件循环层挂起，零线程资源占用。
- 非流式端点：`try/finally` 保证锁必然释放。
- 流式端点：锁的生命周期绑定到 SSE `StreamingResponse` 生成器的 `finally` 块，彻底防止多客户端竞态导致的写乱序。
- 会话删除时自动从锁字典中清理对应条目，防止长期运行内存增长。

### 3. 自愈式向量维度对齐

- `RobustOpenAIEmbeddingFunction` 带静态维度缓存，能识别模型名（如 `doubao-*` → 1024 维）并在 API 故障时提供精准维度的零向量 Fallback。
- 获取 ChromaDB Collection 时主动探测已有文档的实际向量长度并强制对齐，根治切换模型或 API 重启后的维度不匹配崩溃。

### 4. 长期记忆 RAG 管道

- 每个角色拥有专属 ChromaDB Collection，按 Persona 隔离存储。
- 祖先链检索使用单次 SQLite CTE 递归查询，规避 N+1 查询问题。
- 混合打分精排：**余弦相似度（60%）+ 内容重要性（20%）+ 时间衰减（20%）**，子会话条目额外施加代际惩罚权重。
- 所有权重、半衰期、候选倍数均可在 `config.yaml` 中调整，无需重启即可通过 API 热更新。

### 5. 会话继承树（分叉剧情线）

- 支持从任意历史会话 fork 出子会话，继承好感度、认知状态、当前场景。
- 删除中间节点时自动将子节点重连到父节点，继承链不断裂。
- RAG 检索跨代际透明合并，代数越远权重越低。

### 6. 认知与好感度闭环

- **记忆提纯**：对话满足条数阈值后自动（或手动）触发，LLM 提炼近期对话为结构化记忆条目，写入 SQLite + ChromaDB 双存储。
- **认知更新**：基于高重要性记忆定期更新角色的自我认知状态文本（`cognition_state`）。
- **好感度回滚**：删除 assistant 消息时自动逆向回滚好感值与心情状态。

### 7. 零依赖 SillyTavern Card V2 解析器

- 支持 PNG（`tEXt` / `zTXt` / `iTXt`）和 JSON 格式，无需第三方图像库。
- 兼容 V1 / V2 规范及各平台变种字段。
- 入库时自动将角色卡内的 HTML 标签清洗为 Markdown，降低 Token 消耗并防止注入。

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
  chat_model: deepseek-v4-pro          # 主（思考）模型
  non_reasoning_chat_model: deepseek-v4-flash  # 快速模型
  memory_model: deepseek-v4-flash      # 记忆提纯专用模型
  embedding_model: doubao-embedding-vision-251215
  chat_base_url: https://api.deepseek.com/v1
  embedding_base_url: https://ark.cn-beijing.volces.com/api/v3
  temperature: 0.7
  memory_temperature: 0.3
  max_tokens: 4096
  reasoning_mode: false                # true → 默认使用思考模型
  timeout: 60                          # LLM 请求超时秒数（思考模型建议 ≥60）

app:
  context_history_limit: 15            # 注入 LLM 的最近对话条数
  retrieval_top_k: 3                   # RAG 最终召回条数
  memory_extract_history_limit: 20     # 记忆提纯扫描的历史条数上限
  retrieval_min_importance: 0.3        # 记忆重要性过滤阈值（0~1）
  retrieval_max_distance: 1.2          # 向量余弦距离过滤上限
  cognition_update_interval: 30        # 认知更新触发间隔（消息条数）
  cognition_importance_threshold: 0.8  # 触发认知更新所需的记忆重要性门槛
  cognition_max_words: 200             # 认知状态文本最大字数
  lorebook_scan_depth: 5               # Lorebook 扫描最近 N 条消息
  lorebook_token_budget: 3000          # Lorebook 注入 Token 总预算
  lorebook_max_recursive_passes: 3     # Lorebook 递归触发最大轮数

  # 混合打分权重（三项之和建议为 1.0）
  retrieval_weight_similarity: 0.6
  retrieval_weight_importance: 0.2
  retrieval_weight_time: 0.2
  retrieval_half_life_turns: 50        # 时间衰减半衰期（轮次）
  retrieval_candidate_multiplier: 3    # 粗排候选数 = top_k × multiplier
  retrieval_ancestor_weight: 0.8       # 父代记忆的权重衰减系数

  # 存储路径
  sqlite_db_path: data.db
  chroma_db_path: ./chroma_data
  upload_avatar_dir: ./assets/avatars

  # 安全与限制
  cors_origins:
    - "*"                              # 生产环境建议改为具体域名
  max_card_size_mb: 10

  # 历史消息拉取
  history_fetch_default: 50
  history_fetch_max: 500
```

### 动态可调参数（通过 `PUT /utils/settings` 无需重启）

`temperature` · `max_tokens` · `reasoning_mode` · `context_history_limit` ·  
`retrieval_top_k` · `retrieval_min_importance` · `retrieval_max_distance` ·  
`lorebook_scan_depth` · `lorebook_token_budget` · `lorebook_max_recursive_passes` ·  
`cognition_max_words` · `retrieval_half_life_turns` · `retrieval_candidate_multiplier`

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

### 角色卡管理 `/characters`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/characters/parse` | 解析 PNG/JSON 角色卡，返回结构化数据（不入库） |
| POST | `/characters/create` | 将角色数据存入数据库 |
| GET | `/characters` | 获取所有角色简要列表 |
| GET | `/characters/{id}` | 获取角色完整设定 |
| PUT | `/characters/{id}` | 更新角色设定 |
| DELETE / POST | `/characters/{id}` 或 `/characters/{id}/delete` | 级联删除角色、所有会话及 ChromaDB 向量集合 (POST 用于移动端及网关避让) |

### 会话管理 `/sessions`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/sessions/create` | 新建会话（指定 `parent_session_id` 则继承分叉） |
| GET | `/sessions` | 查询角色的所有会话列表 |
| GET | `/sessions/{id}` | 获取会话详情（含 Persona 完整状态） |
| GET | `/sessions/{id}/history` | 获取会话聊天历史（支持 `limit` 参数） |
| PUT | `/sessions/{id}/title` | 修改会话标题 |
| DELETE / POST | `/sessions/{id}` 或 `/sessions/{id}/delete` | 安全删除会话，自动重连子节点继承链 (POST 用于移动端及网关避让) |
| POST | `/sessions/{id}/trigger_summary` | 手动触发记忆提纯 |
| POST | `/sessions/{id}/trigger_cognition` | 手动触发认知状态更新 |
| PUT | `/sessions/messages/{message_id}` | 编辑消息内容 |
| DELETE / POST | `/sessions/messages/{message_id}` 或 `/sessions/messages/{message_id}/delete` | 删除消息（自动回滚好感度与心情状态，POST 用于移动端及网关避让） |

### 对话核心 `/chat`

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/chat` | 非流式对话（等待完整回复） |
| POST | `/chat/stream` | SSE 流式对话（逐 chunk 推送） |

两个端点均支持以下请求体：

```json
{
  "session_id": 1,
  "user_message": "你好",
  "use_reasoning": null,
  "is_regenerate": false
}
```

- `use_reasoning`：`true` 强制思考模型，`false` 强制快速模型，`null` 沿用 `config.yaml` 设置。
- `is_regenerate`：`true` 时忽略 `user_message`，重用数据库中最后一条用户消息重新生成回复。

---

## 目录结构

```
app-backend/
├── main.py                  # 启动入口，路由注册，CORS
├── config.yaml              # 非敏感运行时配置
├── .env                     # 敏感密钥（不提交）
├── requirements.txt
│
├── core/
│   ├── models.py            # SQLAlchemy ORM 模型定义
│   ├── database.py          # 数据库连接与 Session 工厂
│   ├── config.py            # Settings 类，加载 .env + config.yaml
│   ├── auth.py              # X-API-Key 鉴权依赖
│   ├── locking.py           # 会话级 asyncio.Lock 管理
│   └── utils.py             # 工具函数（获取本机 IP 等）
│
├── routers/
│   ├── chat.py              # /chat 与 /chat/stream 端点
│   ├── sessions.py          # /sessions 端点
│   ├── characters.py        # /characters 端点
│   └── utils.py             # / 与 /utils 端点
│
├── services/
│   ├── chat_engine.py       # LLM 调用、Prompt 组装、流式封装
│   ├── memory_manager.py    # RAG 检索、记忆存储、外观层入口
│   ├── cognition_service.py # 记忆提纯、认知更新
│   ├── lorebook_engine.py   # 世界书关键词匹配与注入
│   ├── ahocorasick.py       # Aho-Corasick 自动机实现
│   ├── session_service.py   # 会话删除与继承链重连
│   └── parse.py             # SillyTavern 角色卡解析
│
├── schemas.py               # Pydantic 请求/响应模型
└── assets/
    └── avatars/             # 上传的头像文件
```

---

## 测试

```bash
# 世界书独立单元测试
python test_lorebook.py

# 记忆提纯与 RAG 闭环测试
python test_closed_loop_memory.py

# 会话树重连与 API 集成测试
python test_api.py
```

---

## 注意事项

- **本项目为单用户私有部署设计**，数据库无用户隔离，请勿直接暴露到公网（建议设置 `ACCESS_API_KEY` 或套一层反向代理）。
- **移动端与 Nginx 兼容（DELETE 降级避让）**：为防范移动原生客户端及 Nginx 反向代理层在 HTTP 强跳转 HTTPS 时自动将 `DELETE` 重定向并降级为 `GET` 的现象，所有的物理删除接口均已挂载 `DELETE` 和 `POST .../delete` 双通道路径。移动端开发或联调时推荐统一走 `POST .../delete` 通道。
- 上传的头像/角色卡文件名会自动加 UUID 前缀防止同名覆盖，原始文件名保留在后缀。
- LLM 超时默认 60 秒，可在 `config.yaml` 的 `timeout` 字段调整；思考模型（如 DeepSeek-R1）首 token 延迟较长，建议不低于 60 秒。
- ChromaDB 数据位于 `./chroma_data/`，SQLite 数据位于 `./data.db`，备份时两者一并保存。
