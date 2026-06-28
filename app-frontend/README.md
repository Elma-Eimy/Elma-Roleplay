# AI Roleplay Frontend App

> 基于 **Uni-app (Vue 3) + Vite + Pinia + TypeScript + UnoCSS** 构建的跨平台 AI 角色扮演移动客户端。
> 适配移动端 App (iOS/Android)、微信小程序及 H5 浏览器环境，提供角色对话、世界书编辑、剧情分支继承、记忆与图谱浏览以及配音朗读体验。

---

## 目录

- [技术栈](#技术栈)
- [核心功能](#核心功能)
- [快速开始](#快速开始)
- [目录结构](#目录结构)
- [核心工程踩坑与 Hack 指引](#核心工程踩坑与-hack-指引)
- [生产部署](#生产部署)

---

## 技术栈

| 框架/工具 | 技术选择 | 作用 |
|------|------|------|
| **应用框架** | Uni-app (Vue 3) | 跨平台一次编写，多端发行（App/小程序/H5） |
| **构建工具** | Vite 5.x | 超高速的热更新（HMR）开发体验 |
| **状态管理** | Pinia | 轻量化、强类型支持的响应式状态管理（Chat & Persona 状态维护） |
| **样式编译** | UnoCSS | 兼容 Tailwind CSS 的原子化 CSS 引擎，打包体积小，编译速度快 |
| **逻辑语言** | TypeScript 4.x/5.x | 全局类型保障，对接后端数据接口定义 |
| **编译检查** | vue-tsc | 开发与打包前期的 Vue 单文件组件静态类型校对 |

---

## 核心功能

### 1. 角色扮演对话流
* **富文本状态反馈**：气泡对话形式展现，直接渲染出 AI 角色当前的**情绪标签（Emotion Tag）**及**好感度变动（Affection Score）**。
* **语音朗读**：与后端 TTS 服务对接，支持 AI 消息生成后自动或手动播放语音，可配置过滤动作描写。

### 2. 多分支会话与多候选版本管理
* **多版本候选回复切换 (Swipe Paging / Candidates)**：包含多候选版本的 AI 消息，对话气泡底部会显示翻页指示器（如 `1 / 3`）。支持在气泡上左右滑动或点击翻页，调用后端 `POST /chat/switch_candidate` 接口。
* **震动反馈与联动更新**：切换候选版本时支持震动反馈（`uni.vibrateShort`），对应的消息文本、好感变动、情绪标签及语音播放路径会同步更新。
* **剧情分叉 (Fork)**：支持从任意一条特定消息分叉出子会话，继承之前的状态（好感、心情、认知等）。
* **分支跳转**：支持切换不同的分支会话（Session），历史消息拉取自动向上回溯祖先链。

### 3. 输入与置底滚动
* **滚动置底（Reactivity Hack）**：在 [useChatScroll.ts](file:///g:/APP/app-frontend/src/composables/useChatScroll.ts) 中通过微调值确保每次赋值不同，避免被 Vue 的 Diff 拦截，以触发 DOM 重新滚动定位。
* **软键盘弹起防遮挡**：在 iOS/Android 平台根据系统键盘事件调整滚动位置，避免键盘展开遮挡输入框。

### 4. SillyTavern 角色卡导入
* **卡片元数据解析**：支持上传或拖拽 SillyTavern 规格的 PNG 角色卡或 JSON 文件，前端读取元数据并转入创建页。

### 5. 独立世界书编辑器 (Lorebook Editor)
* **图形化管理条目**：提供完整的世界书管理界面，可视化创建、删除世界书，并能为条目配置激活关键词、常量激活、触发权重等复杂规则。
* **角色绑定**：支持将不同的独立世界书与特定角色卡进行多对多绑定与解绑。

### 6. 引擎参数微调与记忆/提示词审查工具
* **记忆与图谱管理**：
  * 支持直接查看后端从对话提纯出的语义记忆列表（`MemoryChunks`）。
  * 允许用户直接**手动添加、更新、删除**会话的专属向量记忆。
* **Prompt 组装预览**：调试模式下，可一键获取并预览最近一轮提交给大模型的完整 System Prompt 拼接详情，包含所有被世界书或 RAG 激活的上下文文本。
* **参数调整**：支持在设置面板调整大模型温度（`temperature`）、上下文携带量、RAG 检索阈值、AC 自动机深度等后端运行时参数。

---

## 快速开始

### 1. 安装项目依赖

```bash
# 进入前端文件夹
cd app-frontend

# 安装依赖
npm install
```

### 2. 运行开发环境

```bash
# 启动并运行于浏览器（H5 端）
npm run dev:h5

# 编译为微信小程序（并在微信开发者工具中导入 dist/dev/mp-weixin 文件夹）
npm run dev:mp-weixin

# 运行自定义多端服务
npm run dev:custom
```

### 3. 配置连接参数

打开运行成功后的页面：
1. 点击底栏的 **“设置”** 选项卡。
2. 找到 **“服务器连接配置”**，填写您的后端 API 地址（例如本地局域网地址 `http://192.168.1.x:8000`）。
3. 如果后端开启了鉴权，请填写对应的 `X-API-Key` 密钥（保存在本地 LocalStorage 中，不会泄露）。

---

## 目录结构

```
app-frontend/
├── package.json
├── tsconfig.json
├── vite.config.ts           # Vite 构建配置（含 UnoCSS 动态导入）
├── uno.config.ts            # UnoCSS 预设与自定义规则
├── index.html
│
├── src/
│   ├── main.ts              # 应用初始化入口
│   ├── App.vue              # App 根组件
│   ├── pages.json           # Uni-app 路由与页面风格配置文件
│   ├── uni.scss             # 预置 UI 样式定义
│   │
│   ├── pages/               # 视图层页面
│   │   ├── index/           # 首页：会话列表、最近联络历史
│   │   ├── chat/            # 聊天主页面：对话流展现、语音播放、分支树控制
│   │   ├── character/       # 角色卡模块（列表、详情展示、导入与新建）
│   │   └── settings/        # 系统设置页、API 配置、以及独立的 Lorebook（世界书）编辑模块
│   │
│   ├── components/          # 公用 UI 组件
│   │   ├── chat/            # 对话泡泡、控制面板
│   │   ├── character/       # 角色卡片骨架
│   │   └── common/          # 弹窗、加载中等通用小组件
│   │
│   ├── composables/         # 逻辑组合层
│   │   ├── useChatScroll.ts # 滚动置底、软键盘弹起防御 Hack
│   │   └── useAudioPlayer.ts# TTS 音频流播放控制器
│   │
│   ├── store/               # Pinia 状态仓库
│   │   ├── chatStore.ts     # 当前活跃会话数据与消息队列
│   │   └── personaStore.ts  # 好感度、认知与当前角色微观状态缓存
│   │
│   └── api/                 # 封装 Axios / uni.request
│       ├── config.ts        # 全局 Axios 拦截器与 Key 挂载
│       ├── chat.ts          # 对话与 Swipe 候选请求接口
│       ├── sessions.ts      # 会话、消息及向量记忆增删改查接口
│       ├── characters.ts    # 角色卡创建与删除接口
│       └── settings.ts      # 引擎参数获取与热更新更新接口
```

---

## 核心工程细节与兼容性处理

为了保证跨端兼容性和移动端体验，项目前端针对一些兼容性问题作了特殊处理，开发维护时请留意：

### 1. UnoCSS 与 uni-app 的 ESM 模块加载冲突
在 `vite.config.ts` 中，我们**没有**采用静态 `import UnoCSS from 'unocss/vite'`。
* **原因**：uni-app 内置的部分编译加载器基于 CommonJS（CJS），而现代 UnoCSS 是纯 ESM。静态导入会在打包某些非 H5 平台时触发加载冲突导致崩溃。
* **解决方案**：使用异步动态导入包装导出：
  ```typescript
  export default defineConfig(async () => {
    const UnoCSS = (await import("unocss/vite")).default;
    return {
      plugins: [UnoCSS(), uni()]
    }
  });
  ```

### 2. 消息流滚动置底问题 (`scrollTop`)
在聊天视图中，我们通过 `:scroll-top="scrollTop"` 动态指定滚动条位置。
* **原因**：当消息流不断涌入，如果重复赋值为固定的大数值（如 `999999`），Vue 会判定新值与旧值相同而不去触发底层 DOM 的更新，导致滚动失效。
* **解决方案**：在 [useChatScroll.ts](file:///g:/APP/app-frontend/src/composables/useChatScroll.ts) 中，通过数学微调值确保每次赋值不同，从而触发 Vue 响应式更新：
  ```typescript
  scrollTop.value = 999999 - Math.random();
  ```

### 3. iOS 键盘弹起的页面挤压与占位符
* 在 Android 平台，我们在 `pages.json` 配置了 `"softinputMode": "adjustResize"`，系统 WebView 会自动缩放高度，无需前端进行动态布局修改。
* 在 iOS 平台，由于系统机制不同，键盘弹起不会改变 WebView 高度。我们必须通过 `uni.onKeyboardHeightChange` 监听到高度，在前端下方放置一个与键盘同高（`keyboardHeight`）的空白 `view` 占位块，来强行把对话框“顶”起来。

### 4. 移动端 HTTPS 重定向下的 DELETE 方法兼容
* 在移动原生 App 或 Nginx 强制将 HTTP 重定向至 HTTPS 时，重定向响应可能导致客户端将 `DELETE` 请求自动转换为 `GET` 请求，导致删除操作失效。
* **处理方案**：前端在调用删除角色、删除会话以及删除消息接口时，支持调用对应的 `POST .../delete` 接口以避开此兼容性问题。

---

## 生产部署

1. **打包 H5 端静态资源**：
   ```bash
   npm run build:h5
   ```
   打包产物将输出在 `dist/build/h5`
2. **打包小程序端（微信）**：
   ```bash
   npm run build:mp-weixin
   ```
   随后用微信开发者工具打开 `dist/build/mp-weixin` 进行上传发布。
3. **打包 App 客户端**：
   需要在 **HBuilderX** 中打开本项目根目录，点击 **发行 -> 原生App-云打包** 即可生成对应的 Android `.apk` 或 iOS `.ipa` 独立包。
