# AI Roleplay Backend Engine — 角色扮演后端核心大脑

这是一个基于 FastAPI、SQLite 和 ChromaDB 构建的高性能异步 AI 角色扮演（AI Roleplay）智能体后端。项目实现了高精度角色模拟、基于 RAG 的长期记忆检索、分支树状会话流管理以及角色微认知与好感度更新闭环。

---

## 🛠️ 技术栈与系统架构

- **网络框架**：FastAPI (Uvicorn) - 提供基于 Python 异步特性的高并发网络接口。
- **关系型数据存储**：SQLAlchemy (SQLite) - 存储和管理结构化的会话、消息、角色卡配置以及 Persona 情感状态。
- **向量数据库**：ChromaDB - 处理和检索高维嵌入（Embeddings），提供长期记忆检索（RAG）。
- **大模型集成**：兼容 OpenAI API 规范的客户端。

---

## 🚀 核心技术特性

### 1. 零依赖 SillyTavern Card V2 PNG 卡片解析器
- 原生支持 SillyTavern 角色卡 PNG 格式的元数据解析，无需依赖体积庞大的第三方图像库。
- 深度解析 PNG 数据块，包括 `tEXt`、经 Deflate 压缩的 `zTXt` 以及 `iTXt`（国际 UTF-8）格式。
- 在数据入库阶段自动将 HTML 标签清洗为轻量化 Markdown，有效降低 LLM 上下文 Token 损耗并杜绝系统注入风险。

### 2. 长期记忆检索（RAG）管道
- 为每个角色动态挂载专属的 ChromaDB 向量集合，构建其长期记忆上下文。
- 结合余弦距离、内容重要性评分和 Token 预算，精准筛选并召回最相关的背景记忆切片。
- 引入异步记忆提纯机制，在用户消息达到预设阈值时，自动通过后台任务从历史对话中提炼出记忆事件并写入向量数据库。

### 3. Git 式树状分支会话管理
- 支持树形结构的会话继承，玩家可以从现有对话的任意节点分叉（Fork）出子会话（`parent_session_id`），继承并无缝衔接历史消息。
- 采用级联生命周期安全算法：在删除某一会话时，其子节点会自动向上挂载到祖先节点，维护时间线和引用关系的完整性。

### 4. 异步认知与好感度动态闭环
- 系统实时从角色视角评估对话并计算情感及好感度增量（`affection_change` 范围为 `-5` 到 `+5`）。
- 运用 FastAPI 的 `BackgroundTasks`，在不阻塞当前响应的前提下，异步提纯长期记忆并实时重构角色的微观“认知状态”（Cognition State）。

### 5. 高容错流式 JSON 解析器
- 采用 Server-Sent Events (SSE) 协议进行超低延迟流式响应。
- 内置流式状态机，能在 LLM 吐出 JSON 的过程中，字符级地实时提取并渲染 `"reply"`、`"emotion_tag"`、`"affection_change"` 等参数。
- 即使大模型返回的 JSON 结构发生部分损坏，也能自动回退至原始文本直出机制，保障服务不中断。

---

## 📋 API 快速参考

### 通用与系统工具
- `GET /` - 服务健康度检查。
- `POST /upload/avatar` - 上传角色头像资产。
- `GET /utils/settings` - 获取当前的全局模型生成与检索参数。
- `PUT /utils/settings` - 动态修改并持久化全局生成与检索设置。

### 角色卡模板管理 (`/characters`)
- `POST /characters/parse` - 解析 PNG/JSON 角色卡元数据（不存入数据库）。
- `POST /characters/create` - 将新角色卡数据存入 SQLite 关系数据库。
- `GET /characters` - 获取所有角色的简明列表。
- `GET /characters/{character_id}` - 查询指定角色的详细配置设定。
- `DELETE /characters/{character_id}` - 级联删除角色卡、关联会话树及 ChromaDB 向量集合。

### 会话与消息管理 (`/sessions`)
- `POST /sessions/create` - 创建全新会话或分叉出的继承子会话。
- `GET /sessions` - 查询指定角色的历史会话树列表。
- `GET /sessions/{session_id}/history` - 按严格时间线顺序召回继承链的对话历史。
- `DELETE /sessions/{session_id}` - 安全删除会话并自动向上重连子会话。
- `POST /sessions/{session_id}/trigger_summary` - 手动强制触发记忆提纯。
- `POST /sessions/{session_id}/trigger_cognition` - 手动强制更新角色认知。

### 对话核心 (`/chat`)
- `POST /chat` - 非流式 RAG 对话接口。
- `POST /chat/stream` - SSE 流式 RAG 对话接口。

---

## 💻 本地部署与调试

### 1. 环境依赖
- Python 3.10 及以上
- SQLite3 运行环境

### 2. 依赖安装
克隆仓库并建立 Python 虚拟环境：
```bash
python -m venv venv
source venv/bin/activate  # Windows 环境下运行: venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 环境变量配置
在后端根目录创建 `.env` 配置文件：
```env
ACCESS_API_KEY=你的访问密钥(开发环境留空即可无密测试)
SECURITY_CORS_ORIGINS=["*"]
OPENAI_API_KEY=大模型服务API_KEY
```

### 4. 运行服务
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
系统启动时将自动识别当前计算机在局域网内的所有活跃 IPv4 地址并打印在控制台上，极大方便了局域网内其他前端真机设备进行直连调试。
