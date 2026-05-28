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

### 1. 缓存友好（Prompt Caching）与多模型兼容的提示词引擎
- **静态人设分离**：重构了提示词拼装，将核心设定、性格、输出格式及对话示例等**纯静态内容**并入主 `system_prompt`，极大化激活了主流 API 的 Prompt Caching。
- **XML 上下文闭包包装**：将当前场景、自我认知、好感状态、世界书知识、召回记忆等**高动态上下文**统一使用 XML 闭包标签包裹，注入到最新一条 `user` 消息尾端。
- **API 交替角色兼容**：严格遵循 `system -> user / assistant -> user` 的角色交替序列，完美兼容 Claude、Gemini 及 DeepSeek 等对 alternating roles 有强限制的 API 节点。

### 2. 线程安全的单会话并发锁（Session Lock）
- 在对话路由中引入了全局线程安全并发锁与 30 秒获取超时机制。
- 对非流式 `/chat` 进行局部锁同步保护与异常释放。
- 对流式 `/chat/stream` 路由实现了**延迟释放机制**，将并发锁的释放生命周期延迟绑定到 SSE `StreamingResponse` 内部生成器的终态 `finally` 块中，彻底杜绝多客户端竞态导致的数据写错乱与对话时序混淆。

### 3. 高容错与自愈式向量维度对齐（Embedding Dimension Self-healing）
- **维度动态缓存与分析**：在 `RobustOpenAIEmbeddingFunction` 中引入静态缓存，且能够智能分析 `model_name`（如自动识别 `doubao` 映射为 `1024` 维），在 API 故障时提供准确维度的零向量 Fallback。
- **Collection 维度主动探测**：获取角色 collection 时，主动查询库中已有文档的向量长度并强制对齐缓存，形成双重防线，根治由于切换模型或 API 故障造成的 ChromaDB `InvalidArgumentError` (维度不匹配) 崩溃。

### 4. 模块化服务层解耦（Facade 设计模式）
为保证代码的可读性和单一职责原则，将原本臃肿的服务文件拆分为以下独立子服务，并通过 `memory_manager.py` 外观层重新导出，保障了上层 API 路由与客户端的 100% 向后兼容性：
- **[lorebook_engine.py](file:///g:/APP/app-backend/services/lorebook_engine.py)**：负责世界书扫描、深度限制、递归解析与 Token 预算控制。
- **[session_service.py](file:///g:/APP/app-backend/services/session_service.py)**：负责会话物理删除、子会话继承关系重连以及 ChromaDB 级联数据一致性清理。
- **[cognition_service.py](file:///g:/APP/app-backend/services/cognition_service.py)**：负责调用 LLM 提纯未总结历史对话、批量上限拦截（防止 Token 爆仓）以及自我认知的演变。

### 5. 零依赖 SillyTavern Card V2 PNG 卡片解析器
- 原生支持 SillyTavern 角色卡 PNG 格式的元数据解析，无需依赖体积庞大的第三方图像库。
- 深度解析 PNG 数据块，包括 `tEXt`、经 Deflate 压缩的 `zTXt` 以及 `iTXt`（国际 UTF-8）格式。
- 在数据入库阶段自动将 HTML 标签清洗为轻量化 Markdown，有效降低 LLM 上下文 Token 损耗并杜绝系统注入风险。

### 6. 长期记忆检索（RAG）管道
- 为每个角色动态挂载专属的 ChromaDB 向量集合，构建其长期记忆上下文。
- 采用一次性 SQLite CTE 递归查询（规避 N+1 查询瓶颈）抓取祖先链。
- 结合余弦距离、内容重要性评分和逻辑时间衰减进行**混合打分精排**。针对 `fact`（客观事实）长期记忆采取温和衰减底数（`0.95`），对分叉后的新线（子会话）进行代数递减惩罚。

---

## 📋 API 快速参考

### 通用与系统工具
- `GET /` - 服务健康度检查。
- `POST /upload/avatar` - 上传角色头像资产。
- `GET /utils/settings` - 获取全局配置参数（支持自定义*遗忘半衰期*、*检索候选倍数*、*单次回复最大 Token* 等）。
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

## 🧪 自动化测试验证

### 1. 世界书独立单元测试
```bash
python test_lorebook.py
```
- 测试常驻常开拦截、selective 选择性触发、大小写敏感控制、递归多轮唤醒以及预算限制。

### 2. 闭环记忆提纯与 RAG 回溯测试
```bash
python test_closed_loop_memory.py
```
- 模拟端到端用户流：发送事实（"我叫小明我喜欢草莓蛋糕"） $\rightarrow$ 手动触发记忆提纯 $\rightarrow$ 直查校验 SQLite 与 ChromaDB 数据是否落库 $\rightarrow$ 检索精排打分断言 $\rightarrow$ 向 AI 发问检验 RAG 回传，实现 100% 数据流闭环验证。

### 3. 会话树重连与 API 集成测试
```bash
python test_api.py
```
- 覆盖角色创建、多轮上下文聊天、会话继承、分支删除重连等完整业务路径。

---

## 💻 本地部署与调试

### 1. 环境准备与安装
```bash
python -m venv venv
venv\Scripts\activate  # Unix 运行: source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置 `.env` 与 `config.yaml`
- 创建并配置 `.env` 文件（参照项目中的只读环境变量）。
- 启动服务：
```bash
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```
 G:\APP\app-backend\config.yaml
