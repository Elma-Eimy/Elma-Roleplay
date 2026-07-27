# AI Roleplay Frontend

面向手机端的跨平台 AI 角色扮演客户端，基于 Vue 3、uni-app、Vite、Pinia 和 TypeScript 构建，可运行于 Android/iOS App、H5 与微信小程序。

界面采用“清新角色画册 + 柔光叙事聊天”的视觉方向：首页用于继续故事，角色库用于浏览人物，聊天页聚焦长篇阅读，人物详情则以档案、世界、记忆和故事线组织内容。

## 功能概览

- 流式角色对话、Markdown 消息与思考内容展示
- 情绪、好感度、认知状态与长期记忆管理
- 多候选回复切换、消息重生成和 TTS 语音朗读
- 从历史消息创建故事分支，并通过分支树切换时间线
- 创建、编辑和导入 PNG/JSON 角色卡
- 人物档案、角色专属世界书及公共世界书绑定
- SillyTavern JSON 世界书导入、编辑和词条管理
- Prompt 组装结果预览与模型生成参数配置
- 运行时服务器地址和 `X-API-Key` 配置
- App、H5、微信小程序三端构建

## 界面结构

| 区域 | 用途 |
| --- | --- |
| 故事首页 | 最近故事、角色横廊、快捷创建与导入 |
| 角色画册 | 浏览角色卡、进入人物档案、创建新角色 |
| 人物档案 | 查看档案、世界设定、记忆入口与故事线 |
| 叙事聊天 | 阅读和发送消息、切换候选、管理分支与状态 |
| 设置 | 外观、模型、记忆与世界、连接安全、数据管理 |

应用使用统一的语义颜色、圆角、间距、按钮和状态组件，并支持系统“减少动态效果”偏好。加载、空数据、错误与离线状态采用一致的视觉反馈。

## 技术栈

| 技术 | 用途 |
| --- | --- |
| Vue 3 + Composition API | 页面与组件开发 |
| uni-app | App、H5、小程序跨端运行 |
| Vite 5 | 开发服务器与构建 |
| Pinia | 会话、角色和聊天设置状态管理 |
| TypeScript | 类型约束与接口定义 |
| markdown-it | 安全 Markdown 渲染 |
| vue-tsc | Vue 单文件组件类型检查 |

项目当前使用组件内 CSS 与 `src/App.vue`、`src/uni.scss` 中的语义设计变量，没有启用 UnoCSS。

## 快速开始

### 环境要求

- Node.js 当前 LTS 版本
- npm
- 可访问的配套后端 API；也可以在源码中启用本地 Mock 模式
- App 调试与发行需要 HBuilderX
- 微信小程序预览需要微信开发者工具

### 安装依赖

```bash
npm install
```

### 启动开发环境

```bash
# H5
npm run dev:h5

# 微信小程序
npm run dev:mp-weixin

# App Plus CLI 编译
npx uni -p app-plus
```

微信小程序开发产物位于 `dist/dev/mp-weixin`。App 端也可以直接通过 HBuilderX 导入项目后运行。

## 后端连接

默认 API 地址为：

```text
http://127.0.0.1:8000
```

可以通过环境变量设置初始地址：

```dotenv
VITE_API_BASE_URL=http://192.168.1.100:8000
```

也可以在应用内进入：

```text
设置 → 连接与安全 → 服务器连接地址
```

应用内保存的地址优先于环境变量。如果后端配置了访问控制，请在同一区域填写对应的 `X-API-Key`；地址和密钥保存在当前设备的 uni-app 本地存储中。

完整接口约定见 [`API_TABLE.md`](API_TABLE.md)。

### Mock 模式

本地 Mock 数据开关位于 `src/api/config.ts`：

```ts
export const USE_MOCK = false;
```

将其改为 `true` 后，角色、会话、消息和世界书会使用本地存储中的示例数据。设置页的“数据管理”可以重置这些 Mock 数据。

## 常用命令

```bash
# 类型检查
npm run type-check

# H5 生产构建
npm run build:h5

# 微信小程序生产构建
npm run build:mp-weixin

# App Plus 生产构建
npx uni build -p app-plus
```

提交前建议依次运行类型检查和三个目标平台构建。对应产物位于：

- `dist/build/h5`
- `dist/build/mp-weixin`
- `dist/build/app`

## 项目结构

```text
src/
├── api/                    # 请求封装、接口类型、运行时连接与 Mock 数据
├── components/
│   ├── character/          # 人物档案与角色世界书
│   ├── chat/               # 消息、输入框、抽屉、记忆与故事分支
│   └── common/             # 页面头部、按钮、状态、TabBar 与通用弹窗
├── composables/            # 聊天滚动与音频播放等组合逻辑
├── pages/
│   ├── index/              # 故事首页
│   ├── character/          # 角色画册、人物档案与角色编辑器
│   ├── chat/               # 叙事聊天页
│   └── settings/           # 设置与世界书管理
├── store/                  # Pinia 状态仓库
├── App.vue                 # 全局语义变量、基础样式与动效降级
├── pages.json              # 页面与原生 TabBar 配置
└── uni.scss                # uni-app 与应用级 SCSS 变量
```

## 跨端注意事项

- App 端选择角色卡时使用相册中的原始 PNG，以免系统压缩破坏卡片元数据；H5 等平台可选择 PNG 或 JSON。
- App 端流式响应通过 renderjs/XHR 桥接，并继续使用请求头传递 `X-API-Key`。
- Android 聊天页使用 `adjustResize` 适配软键盘；iOS 通过键盘高度监听补偿输入区。
- 音频资源属于受保护接口时，同样通过请求头携带 `X-API-Key`。
- 自定义 TabBar 会隐藏 uni-app 原生 TabBar，页面底部布局需要保留安全区和导航高度。

## 发布

H5 和微信小程序使用上面的生产构建命令。App 发行建议在 HBuilderX 中打开项目，选择“发行 → 原生 App 云打包”，生成 Android 或 iOS 安装包。
