# 项目协作约定

适用于整个仓库。默认使用中文沟通和维护说明文档；代码命名与格式遵循所在模块的现有风格。

## 项目与入口

这是面向单用户私有化部署的 AI 角色扮演应用，前后端由根目录的同一个 Git 仓库管理。

- `app-backend/`：FastAPI、SQLAlchemy、SQLite、ChromaDB；负责对话、Prompt、世界书、记忆、图谱与 TTS。
- `app-frontend/`：Vue 3、uni-app、TypeScript、Pinia；目标平台为 H5、App 和微信小程序。
- 修改前先阅读相关模块及其测试，避免仅凭 README 推断实现。项目概览见 [README](README.md)，文档入口见 [文档导航](docs/README.md)，按任务定位代码和测试见 [Agent 上手指南](docs/guides/AGENT_ONBOARDING.md)。
- 模块分层见 [后端架构](docs/architecture/BACKEND.md) 与 [前端架构](docs/architecture/FRONTEND.md)，前端 API 边界见 [API 模块约定](app-frontend/src/api/README.md)。细节在对应文档维护，本文件只保留执行约定。

## 开发与模块边界

- 保持改动聚焦，不将无关重构、依赖升级或全库格式化混入任务。
- 后端 `routers/` 负责 HTTP 契约和异常转换，业务编排与查询放在对应 `services/` 领域模块；应用装配与后台任务生命周期放在 `application/`。保持 `main.py` 为轻量 ASGI 入口。
- 前端请求通过 `src/api/` 对应领域模块与统一连接配置处理；新代码直接从领域模块导入函数，从 `src/types/` 导入类型。保留现有兼容导出，除非任务明确要求移除。
- 接口变更同时核对后端路由与请求模型、前端类型与调用方、相关 Mock 行为；Mock 不视为后端全部业务规则的完整实现。
- UI 优先复用现有语义变量、通用组件和状态反馈，保持移动端阅读体验、安全区与减少动画适配。
- 文件名与导入路径保持精确大小写一致；跨端代码沿用 uni-app 条件编译与平台适配，避免将浏览器专用能力直接用于所有平台。

## 核心行为约束

- 会话历史、候选回复、记忆与图谱检索必须遵守故事线和 `fork_message_id` 边界，不能读入其他平行分支或分叉后的祖先未来内容。
- 候选切换遵守最新未确认轮次的规则；记忆提纯仅处理已由下一轮用户消息确认的 active 对话。涉及消息、候选或分支修改时，核对好感度、心情、认知与音频关联。
- 对话失败和取消时保持事务清理与会话锁释放；前端切换会话或退出后，旧请求和旧流回调不能覆盖新状态。不要通过重复发送聊天 POST 恢复流式传输。
- 三端 SSE 协议继续由 `src/utils/chatStreamProtocol.ts` 统一解析，App 通过现有 renderjs 桥接和传输模块接入。
- Prompt 改动保持静态设定与动态背景分离、用户原话独立、PHI 与最终输出契约后置；保留角色卡 Prompt DSL 和现有解析兼容性。具体规则见后端 README 与对应回归测试。
- SQLite 是持久业务数据来源，ChromaDB 是可重建的检索索引；外部同步与资源回收沿用 Outbox 的幂等重试机制。
- 数据表结构变更同时更新 ORM 和 Alembic 迁移；保留已有迁移链与旧库升级路径，不以清库代替迁移。
- 访问凭据沿用 `X-API-Key` 请求头，不放入 URL、日志或提交内容。

## 常用命令与验证

命令在对应组件目录执行，优先使用已有依赖环境。后端安装与配置见 `app-backend/README.md`，前端见 `app-frontend/README.md`。

| 工作目录 | 命令 | 用途 |
| --- | --- | --- |
| `app-backend/` | `uvicorn main:app --reload` | 本地后端开发，启动会执行迁移并运行 Worker |
| `app-backend/` | `python -m tests` | 全部隔离自动回归 |
| `app-backend/` | `python -m tests --group memory` | 单领域隔离回归，替换为相关领域 |
| `app-backend/` | `python -m tests --group conversation --pattern test_branch_context_boundary.py` | 单模块隔离回归示例 |
| `app-frontend/` | `npm run dev:h5` | H5 开发服务 |
| `app-frontend/` | `npm test` | 离线自动回归 |
| `app-frontend/` | `npm run type-check` | TypeScript / Vue 类型检查 |
| `app-frontend/` | `npm run build:h5` | H5 生产构建 |
| `app-frontend/` | `npx --no-install uni build -p app-plus` | App Plus 生产构建 |
| `app-frontend/` | `npm run build:mp-weixin` | 微信小程序生产构建 |

- Windows 未激活后端虚拟环境时，将 `python` 替换为 `.\venv\Scripts\python.exe`。
- 后端自动测试优先使用 `python -m tests` 入口：它会复制源码到临时目录、生成测试配置并迁移临时库，不使用开发数据库或真实模型。直接运行 `unittest` 会跳过该隔离。
- 后端行为变更新增或更新对应领域的有效回归，先运行相关领域测试；移动后端模块或改变启动、迁移、共享基础设施时运行完整后端回归，并核对测试临时副本的复制范围。
- 前端逻辑改动运行 `npm test` 和 `npm run type-check`；跨端网络、流式传输、平台适配或共享界面改动按影响执行三个目标平台构建。真机行为不能仅凭构建成功认定通过。
- 纯文档变更核对内容、路径与差异即可。交付时说明实际验证结果；未执行、依赖缺失或失败的检查明确注明，不声称通过。

## 本地数据与手动操作

- 不将 `.env`、真实密钥、本地数据库、ChromaDB 数据、头像、音频或个人配置复制到测试夹具或提交中。
- 不为验证代码重置现有数据。`tests/manual/` 和 `scripts/` 中部分命令会调用真实服务或写删当前数据库；执行前阅读脚本并使用独立测试配置和数据，具体见各自 README。
- `docs/local/` 是 Git 忽略的个人草稿与第三方参考，不作为项目实现或接口契约的权威来源。

## 文档同步

- HTTP 接口契约统一维护在根目录 `API_TABLE.md`；涉及记忆筛选、统计或继承规则时同步更新 `docs/api/MEMORY_API.md`。
- 启动、测试、目录或职责变更更新相应组件 README 与架构说明，不在前后端重复维护 API 总表。
- 新增功能、修复或工程调整在 `docs/changelog/YYYY-MM.md` 按日期倒序记录，每项用 1–2 条简述；根 `CHANGELOG.md` 只保留最多 10 条近期摘要和按年分组的月度索引，超限移除最旧摘要。跨月创建新文件并更新索引，完整历史保留在月度文件中。
- 新增文档同步 `docs/README.md` 导航；月度更新记录由根 `CHANGELOG.md` 索引，无需逐月重复登记到文档导航。文档链接使用仓库相对路径。
- 文档按 `docs/README.md` 的用途分类：当前行为放 `features/`，模块职责放 `architecture/`，未完成规划放 `plans/`；移动文档同步修正引用，避免将待办当作已实现契约。
