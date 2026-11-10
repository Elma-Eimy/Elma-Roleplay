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

群聊详情复用 `ChatHeader.vue`、`ChatComposer.vue` 和 `useChatScroll.ts`，固定输入区，按时间顺序显示轮次。`ChatTranscriptMessage.vue` 提供不访问单聊 Store 的展示组件，与 `ChatBubble.vue` 共用 `chatMessage.css` 和 `utils/markdown.ts` 的 Markdown 渲染。两种聊天共用 `ChatSceneBackground.vue`、`ChatReadingPreferences.vue`、聊天页阅读样式与 `chatDrawer.css` 抽屉样式；字号、行距、小说/气泡排版与色调沿用同一阅读设置。群聊背景使用当前采用的立绘，可跟随最后发言成员或固定成员，图片失败回退头像；候选预览不会改写背景。抽屉分成员、外观、起点和管理，候选预览使用独立面板。

群聊页面由 `pages/group/` 提供，继续由 `useGroupSessions.ts` 和 `useGroupRoundFlow.ts` 管理请求与候选生命周期。`components/chat/GroupUtterances.vue` 只展示按 Persona 匹配头像的发言正文，共用于采用内容和候选预览，不负责提交、轮询或状态重放。入群资料与候选状态仍显式区分，完整界面批次见 [M6 计划](../plans/group-chat/M6_INTERFACE_AND_ACCEPTANCE.md)。

`GroupMemberStates.vue` 共用于当前采用状态和候选预览，按成员展示状态、继承认知与候选可用的个人认识，不发起请求。`useGroupRoundFlow.loadAdoptedState()` 独立保存当前采用状态，按群版本、最新轮次/候选及 revision 校验读取结果；选择或确认变化、处理操作、离页和切服使旧数据与在途读取失效。读取不改变采用选择、不派发模型，也不影响原有候选预览。

`useGroupPortraits.ts` 管理成员立绘查询、素材分页与一次性选择写入，复用群聊详情的页面/服务器代际。写入时暂停旧轮次视图并阻止聊天写操作，结束后通过 GET 重读；不自动重发 PUT，也不调用单聊选择接口。轮次发言和候选状态展示各自快照中的图像，缺失素材及旧响应回退头像。上传和素材管理仍由角色档案负责。

## 流式聊天与会话隔离

群聊通过 `useGroupSessionDetail` 向轮次流程注入模型参数读取函数，复用 `chatSettingsStore` 的故事偏好和 `GenerationSettingsSheet.vue`。只有发送与重生成解析点击时的模型选择；等待期间仍由原流程占用提交状态并检查页面代际，未接受的请求不登记恢复 UUID。续接继续使用后端冻结参数。`useChatScroll` 共用于单聊和群聊，按原生 `height` 或 H5 可见视口计算键盘占位；群聊 App 页面也配置 `adjustResize`。

普通发送从 `store/chatStore.ts` 调用 `api/chat.ts`。H5 与小程序接收逻辑见 `api/chatStream.ts`；App 经 `composables/useChatStreamBridge.ts`、`components/chat/ChatStreamBridge.vue` 与 `api/transports/appStream.ts` 接入。三端共用 `utils/chatStreamProtocol.ts` 解释 SSE 事件和终态。

发送与重新生成在模型配置加载完成、会话上下文校验后，通过 Store 内的 `buildChatRequest()` 统一装配模型、昵称和采样参数；重新生成单独设置标记，消息占位、候选恢复与传输生命周期仍由各自流程协调。

`utils/chatStreamBuffer.ts` 按实例暂存正文和思考分块，共用 48 ms 刷新定时器，并提供立即刷新与丢弃操作。Store 校验占位消息后追加分块，通过回调更新消息；完成前立即刷新，失效、失败、恢复历史或建立新占位时按原流程丢弃暂存内容。缓冲工具不决定消息归属或生成终态。

`chatStore.ts` 使用会话版本和取消对象使旧请求失效。切换故事、退出页面或恢复流时，必须检查迟到的历史响应、流回调和终态能否覆盖当前故事。不要通过重复发送聊天 POST 恢复接收。后端断连后的持久化行为见 [后端架构](BACKEND.md#后台任务)。

编辑、删除和候选切换在发起时捕获故事、会话代际与服务器地址，成功和失败回写均校验上下文。它们返回 `success`、`error` 或 `stale`，迟到结果不修改消息、人格或新任务的加载状态；当前修改失败通过调用方反馈，不使用会终止加载的流错误收尾。

编辑草稿由 `useChatMessageActions` 管理独立版本，只在成功且编辑目标仍匹配时关闭。保存失败保留草稿并显示错误，保存中阻止重复提交；取消、切故事或退出后，旧保存不能关闭新编辑框或清除其忙碌状态。

`api/config.ts` 只有在新服务器地址保存成功且变化时，通过 `utils/connectionEvents.ts` 同步通知活动 Store 和编辑流程。聊天与人物状态重置，页面清空旧故事上下文，恢复轮询停止继续查询；需重新选择新服务器的故事，不复用同号故事。相同地址或保存失败不重置。订阅随对应 Store 或组件作用域释放，旧请求即使在 A→B→A 后返回也不能恢复旧上下文。这些操作停止本地接收和回写，不撤销已经发往后端的写入或后台生成。

## 接口与平台边界

`pages/group/` 提供独立的群聊列表、创建和详情，入口位于故事首页。`composables/useGroupSessions.ts` 管理分页、成员来源、提交与删除；页面只负责展示和导航，不进入单聊聊天 Store。类型与领域 API 沿用 M1-C 的独立模块。

M2-C 在详情增加只读轮次列表，独立的 GroupRound/GroupUtterance 类型保留作者 Persona ID 和轮内 sequence，界面通过成员位置区分同名角色。按整轮加载，保留失败前缀；刷新/翻页错误保留已有内容并重试原页。详情、历史读取各用请求版本，切故事、切服、离页或删除后失效，历史响应不能回填新目标。M4-D 在此基础上增加操作与恢复，Mock 仍仅从独立 groupRounds 集合读取虚构样本，不模拟生成。

详情刷新期间阻止轮次翻页；详情请求结束并解除忙碌后再读取轮次首页，避免翻页占用历史读取忙碌状态而跳过首页刷新。轮次刷新、重试和翻页的界面反馈同时遵守详情忙碌状态。

M3-D 的 `utils/groupRounds.ts` 负责候选状态和停止提示，缺少新增字段的旧响应仍可阅读，未知失败码不直接显示。专用 H5 构建 `VITE_GROUP_PREVIEW=true` 由 Vite 注入标记和构建常量；`api/config.ts` 只在该构建中固定当前页面来源、忽略已存地址/密钥并拒绝写请求。普通构建和 App/小程序继续使用原连接配置，M4-D 的操作入口不改变该只读预览保护。

M4-C 扩展 `api/groupSessions.ts` 与 `types/groupSessions.ts`，提供发送、重生成、续接、选择、撤回以及请求/候选 GET；每次调用只发一次请求，不在 API 层轮询或自动重发。查询 UUID 按路径编码，current、操作 revision 与候选 revision 分开表达；旧 rounds 响应继续兼容。Mock 拒绝新增生成与恢复能力。

M4-D 的 `composables/useGroupRoundFlow.ts` 管理整轮读取、候选预览、一次 POST 与 GET 恢复，详情 composable 提供页面作用域和删除互斥。请求 ID 在发送前按服务器与群聊写入 uni 存储，终态补刷成功才清除；查询错误停止轮询并保留待确认状态，返回页面先恢复请求或服务端活动任务。较旧会话版本及同候选/操作的旧版本快照不能倒退当前状态。

主历史另记已展示的会话与所选候选版本，候选查询或翻页不能替代看到新选择的正文；版本不一致时禁用写操作并提示刷新首页。恢复的后续读取逐次检查原页面与预览版本，不跨页面发起新请求或抢回用户新选预览。删除等待主历史及本机恢复记录读取成功；明确拒绝的请求在清理失败时保留拒绝标记，可以重试本机清理，不再查询未接受 UUID。

群聊流程使用页内版本、活动状态和服务器地址校验回写，订阅 `connectionEvents`，在 onHide/onUnload 及作用域销毁时失效。列表、角色和来源读取各自管理请求版本；创建固定点击时的参数快照，结果不确定时转为先查列表。详情切服后清空目标，不自动读取新服务器的同号故事。删除确认和返回结果均校验原页面与对象版本。该隔离不取消已经发给后端的事务；轮次操作通过持久 UUID 回执恢复，创建与删除保留各自的结果不确定反馈。

`useStoryKeepsakes.ts` 管理本机收藏快照与角色配色，`StoryKeepsakeSheet.vue` 展示回忆册。收藏键包含服务器与故事 ID，配色键包含服务器与角色 ID；换故事或服务器关闭面板并清理当前视图，不继承其他故事的收藏。写入失败保留旧值并反馈，不调用后端或进入记忆检索链路。

服务器地址、`X-API-Key` 与通用请求由 `api/config.ts` 管理。接口变更要同时核对领域 API、`types/`、调用方及对应 Mock；有些功能在 Mock 下明确不支持，不能用离线行为推断后端完整规则。

跨端能力沿用 uni-app 条件编译和现有适配。浏览器的 `fetch`、DOM 与文件能力不能直接推广到 App 和小程序。UI 复用语义变量与通用反馈，保留安全区和减少动画适配。

回归入口见 [前端测试说明](../../app-frontend/tests/README.md)。逻辑变更运行离线测试与类型检查；网络、流式、平台或共享 UI 变更按影响执行三个目标平台构建，真机行为另行验收。

初评发现、已完成的边界修复和后续拆分顺序见 [生命周期评估](../plans/CHAT_LIFECYCLE_REVIEW.md)。继续拆分 Store 的工作尚未实施。
