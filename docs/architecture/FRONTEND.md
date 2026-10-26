# 前端架构与职责

前端使用 Vue 3、uni-app、TypeScript 与 Pinia，面向 H5、App Plus 和微信小程序。环境与构建命令见 [前端说明](../../app-frontend/README.md)，接口拆分规则见 [API 模块约定](../../app-frontend/src/api/README.md)。

## 页面与请求链路

```text
src/main.ts + App.vue + pages.json
  └─ pages/ 页面
       ├─ components/ 展示与交互
       ├─ composables/ 可复用流程
       └─ store/ 跨组件状态与聊天请求生命周期
            └─ api/ 领域请求 → config.ts 连接与认证 → 后端
                         └─ mock/ 离线实现
```

这是职责导读，不是强制每个页面经过 Store：页面和 composable 也会直接调用领域 API。修改前沿实际导入和调用方确认数据流。

| 位置（相对 `app-frontend/src/`） | 职责与阅读入口 |
| --- | --- |
| `pages/` | `index/` 故事首页、`character/` 角色与档案、`chat/` 聊天、`settings/` 设置与世界书 |
| `components/` | `chat/` 对话组件、`character/` 导入与档案组件、`common/` 通用 UI 和反馈 |
| `composables/` | 导入、翻译、音频、记忆整理、状态与立绘选择等交互流程 |
| `store/` | `chatStore.ts` 管理消息和请求失效，`personaStore.ts` 管理角色与当前故事的人格状态，`chatSettingsStore.ts` 管理聊天设置 |
| `api/` 与 `types/` | 领域请求、连接和 Mock 分流；共享类型单独维护，新增调用直接从领域模块导入 |
| `utils/` | SSE 协议、解码、取消、Markdown、角色卡等工具 |
| `App.vue` 与 `uni.scss` | 全局基础样式与语义设计变量；页面专属样式留在对应页面 |
| `api/transports/` | App 流传输适配，配合 renderjs 桥接组件使用 |

## 流式聊天与会话隔离

普通发送从 `store/chatStore.ts` 调用 `api/chat.ts`。H5 与小程序接收逻辑见 `api/chatStream.ts`；App 经 `composables/useChatStreamBridge.ts`、`components/chat/ChatStreamBridge.vue` 与 `api/transports/appStream.ts` 接入。三端共用 `utils/chatStreamProtocol.ts` 解释 SSE 事件和终态。

`chatStore.ts` 使用会话版本和取消对象使旧请求失效。切换故事、退出页面或恢复流时，必须检查迟到的历史响应、流回调和终态能否覆盖当前故事。不要通过重复发送聊天 POST 恢复接收。后端断连后的持久化行为见 [后端架构](BACKEND.md#后台任务)。

## 接口与平台边界

服务器地址、`X-API-Key` 与通用请求由 `api/config.ts` 管理。接口变更要同时核对领域 API、`types/`、调用方及对应 Mock；有些功能在 Mock 下明确不支持，不能用离线行为推断后端完整规则。

跨端能力沿用 uni-app 条件编译和现有适配。浏览器的 `fetch`、DOM 与文件能力不能直接推广到 App 和小程序。UI 复用语义变量与通用反馈，保留安全区和减少动画适配。

回归入口见 [前端测试说明](../../app-frontend/tests/README.md)。逻辑变更运行离线测试与类型检查；网络、流式、平台或共享 UI 变更按影响执行三个目标平台构建，真机行为另行验收。
