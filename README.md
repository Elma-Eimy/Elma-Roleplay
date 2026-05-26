# AI Roleplay System — 智能角色扮演系统主文档

这是一个端到端的 AI 角色扮演（AI Roleplay）应用程序。项目由前端 UniApp 移动端/网页端应用与后端 FastAPI 核心大脑两部分组成，具备深度长期记忆检索（RAG）、动态情感表情渲染、微认知更新等前沿特性。

---

## 📌 项目目录结构

```text
/APP
├── app-backend/       # Python 后端服务核心 (FastAPI + SQLAlchemy + ChromaDB)
└── app-frontend/      # 前端多端应用核心 (Vue 3 + UniApp + TypeScript + UnoCSS)
```

---

## 🏗️ 系统架构图 (System Architecture)

```mermaid
graph TD
    %% Frontend Group
    subgraph Frontend [app-frontend: Vue 3 / UniApp / TS]
        UI[User Interface & Dialog Views]
        EC[Dynamic Emotion Canvas / Diff Expressions]
        LS[Local Storage / Runtime API Config]
    end

    %% Backend Group
    subgraph Backend [app-backend: FastAPI Core Engine]
        API[FastAPI Router Endpoints]
        PNG[Zero-Dependency SillyTavern V2 Parser]
        SSE[SSE Stream / Inline JSON Parser]
        BG[Asynchronous Background Tasks]
    end

    %% Storage Group
    subgraph Storage [Data Layer]
        DB[(SQLAlchemy SQLite: Sessions, Messages, Personas)]
        VDB[(ChromaDB Vector: Long-term Memories)]
    end

    %% LLM Group
    LLM[OpenAI / LLM API Provider]

    %% Relationships
    UI -->|HTTP / SSE Streaming| API
    PNG -->|Card parsing| API
    API -->|Read/Write Session Trees| DB
    API -->|RAG Vector Query| VDB
    API -->|Inference request| LLM
    SSE -->|Stream partial extraction| UI
    BG -->|Asynchronous Memory extraction| DB
    BG -->|Cognitive State compilation| VDB
```

---

## 🌟 核心产品特性

1. **动态情感与差分表情包渲染 (Dynamic Emotion Canvas)**
   - 后端在生成文本的同时，通过大模型自动输出精准的中文 `emotion_tag`（如：开心、生气、平静、害羞等）与好感度增减 `affection_change`。
   - 前端动态监听情感标签，进行差分表情包的平滑切换与预加载，角色神情随对话语境实时变化，无白屏闪烁。

2. **长期与短期记忆双轨引擎 (Hybrid Memory Engine)**
   - **短期记忆**：基于 **SQLite** (`SQLAlchemy`) 存储关系型对话上下文。
   - **长期记忆 (RAG)**：基于 **ChromaDB** 向量数据库，在发送对话时，自动切片并匹配背景设定中相关性最高的人设片段。
   - **记忆提纯**：支持会话级自动/手动触发“记忆提纯”（Memory Compaction），将聊天中产生的核心事件凝结为长期记忆持久化存储。
   - **微认知系统**：实时追踪角色对用户的关系变化，提炼并动态更新角色对用户的独特“认知状态”（Cognition State）。

3. **分支会话继承与级联安全链**
   - 玩家可以在对话的任意一处拉出一条平行时空“子分支会话”，完美继承父会话的历史消息。
   - 提供安全的级联重连算法：当父会话被删除时，子会话会自动向上重新链接到更上一级的祖先会话，保证聊天时间线和引用关系的绝对完整。

4. **开箱即用：局域网零配自动寻址与排错 (LAN Discovery Tool)**
   - 后端启动时会自动探测当前主机在局域网内所有活跃网卡的 IPv4 地址（排除本地回环）。
   - 在控制台中以高可读性的 ASCII 横幅格式打印所有可用的局域网 IP，并附带针对手机联调的详细防火墙和网络配置排错指引，彻底解决联调部署时手机端因输入错 IP 而连不上后端的痛点。

---

## 🛠️ 后端服务部署 (app-backend)

后端采用 FastAPI 框架，底层数据库集成 SQLite 与 ChromaDB 向量检索。

### 1. 环境依赖准备
* 系统要求：Windows / macOS / Linux
* 运行环境：Python 3.10 及以上版本

### 2. 快速启动指南
```bash
# 1. 进入后端根目录
cd app-backend

# 2. 创建并激活虚拟环境 (以Windows为例)
python -m venv venv
venv\Scripts\activate

# 3. 安装依赖包
pip install -r requirements.txt

# 4. 配置环境变量与参数
# 复制或编辑 .env 文件，填写你的大模型 API_KEY 
# 编辑 config.yaml 配置模型名称、嵌入模型及 RAG 检索参数

# 5. 启动服务 (自动监听全网口，提供局域网外部设备访问)
uvicorn main:app --host 0.0.0.0 --port 8000
```

### 3. 部署控制台输出效果
后端成功启动后，将自动呈现以下指引横幅，部署者可直接将局域网 IP 填入前端进行真机联调试玩：
```text
================================================================================
 [OK] AI Roleplay Backend 已成功启动并就绪！
================================================================================
 1. 本地开发调试地址 (当前机器访问):
    -> http://127.0.0.1:8000

 2. 局域网访问地址 (同一 Wi-Fi 或局域网内的手机/其他设备访问):
    -> http://192.168.1.105:8000
    -> http://10.0.0.12:8000

 * 使用提示：
    - 如果在手机 App/小程序中连接此后端，请在设置中输入上述任意一个局域网地址。
    - 确保手机与运行本后端的电脑连接在【同一个 Wi-Fi】下。
    - 若连接失败，请检查电脑防火墙是否允许 8000 端口入站流量。
================================================================================
```

---

## 📱 前端多端部署 (app-frontend)

前端基于 Vue 3 + Vite + TypeScript + UniApp + Pinia 架构，支持编译为小程序、Android APK、iOS App 以及 H5 网页。

### 1. 开发调试
```bash
# 1. 进入前端根目录
cd app-frontend

# 2. 安装项目依赖
npm install

# 3. 运行本地开发服务器 (以编译至H5端为例)
npm run dev
```

### 2. 配置后端连接
项目预留了灵活的后端寻址设置：
* **开发环境默认值**：在开发阶段，前端会自动读取 `import.meta.env.VITE_API_BASE_URL` 或回退至 `http://127.0.0.1:8000`。
* **运行时动态修改**：在应用内的 **设置页面**，用户可以直接修改 **后端 API Base URL**，该配置会即时通过 `uni.setStorageSync` 写入持久化缓存中，所有后续网络请求（`request`）都会自动切换为新地址，非常适合真机局域网部署与切换。

---

## 🔒 网络与防火墙排错指引（极重要）

当在真实手机、Pad 或另一台局域网电脑上测试时，如果无法与后端建立连接，请依次进行如下排查：

1. **统一局域网检查**：请确保手机所连接的 Wi-Fi 与启动后端的电脑处于同一子网。
2. **Windows 防火墙入站规则放行**：
   - 默认情况下，Windows 防火墙可能会拦截未授权的 8000 端口外部入站流量。
   - **解决方法**：打开 `控制面板 -> 系统和安全 -> Windows Defender 防火墙 -> 高级设置 -> 入站规则`，新建一条规则放行 **TCP 协议 8000 端口**，或者允许 `python.exe` 穿越防火墙。
3. **混合内容安全限制（HTTPS H5 专属）**：
   - 如果您把前端打包为了 H5 网页并部署在带有 HTTPS 的域名上，此时浏览器会出于安全策略拦截向局域网 HTTP 后端（`http://192.168.x.x:8000`）发起的明文请求。
   - **解决方法**：推荐使用手机 App/微信小程序调试，或者在浏览器安全选项中为您的测试网站临时勾选“允许混合内容”。
