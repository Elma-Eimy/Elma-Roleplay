# 项目文档导航

新 agent 先读根目录 [协作约定](../AGENTS.md)，再按 [上手指南](guides/AGENT_ONBOARDING.md) 定位任务。本页索引文档；具体规则和命令由对应文档维护。

## 入口与架构

| 文档 | 何时阅读 |
| --- | --- |
| [项目说明](../README.md) | 了解产品能力、技术栈和部署入口 |
| [项目协作约定](../AGENTS.md) | 开工前核对模块边界、行为约束和验证要求 |
| [Agent 上手指南](guides/AGENT_ONBOARDING.md) | 按任务查代码入口、关联文档和回归测试 |
| [后端架构](architecture/BACKEND.md) | 修改应用装配、领域服务、持久化和后台任务 |
| [前端架构](architecture/FRONTEND.md) | 修改页面、状态、请求、跨端传输和 UI |
| [更新日志](../CHANGELOG.md) | 最多 10 条近期摘要与月度归档索引；当前契约仍查接口与领域说明 |

## 当前功能与业务规则

| 文档 | 内容 |
| --- | --- |
| [角色卡导入](features/CHARACTER_CARDS.md) | 格式兼容、中文阅读版本、CHARX 导入与资源生命周期 |
| [模型与思考设置](features/MODEL_SELECTION.md) | 默认模型、故事覆盖、辅助任务模型与兼容 |
| [当前角色状态](features/ROLE_STATE.md) | 增量状态、人工校正、候选与分支恢复 |
| [图谱与记忆一致性](features/GRAPH_MEMORY_CONSISTENCY.md) | 共同事实、联合检索、证据、时间与分叉边界 |
| [进行中事件](features/MEMORY_EVENTS.md) | 跨批事件缓冲、阶段保存、长期准入与重试 |

## 接口契约

| 文档 | 内容 |
| --- | --- |
| [HTTP API 总表](../API_TABLE.md) | 前后端共享的路由清单与领域契约入口 |
| [API 阅读与校验](api/README.md) | 各领域请求、响应、兼容规则的导航及隔离检查方法 |
| [记忆模块 API](api/MEMORY_API.md) | 筛选、统计、继承、导航、整理预览与撤销 |
| [前端 API 模块](../app-frontend/src/api/README.md) | 领域请求封装、共享类型、兼容导出与 Mock 边界 |

## 开发、测试与维护

| 文档 | 内容 |
| --- | --- |
| [后端说明](../app-backend/README.md) | Python 环境、运行配置、Prompt 规则和启动 |
| [后端配置示例](../app-backend/config.yaml.example) | 不含真实凭据的配置示例 |
| [前端说明](../app-frontend/README.md) | 安装、运行时连接、多端开发与构建 |
| [后端测试指南](../app-backend/tests/README.md) | 隔离测试入口、领域分组和手动场景 |
| [前端回归检查](../app-frontend/tests/README.md) | 离线回归、类型检查与跨端验证 |
| [记忆整理质量验收](testing/MEMORY_QUALITY.md) | 固定样本、隔离回放、显式在线验收与人工审阅 |
| [持续集成](development/CI.md) | GitHub Actions 环境、本地文档链接检查、回归范围与失败排查 |
| [后端维护工具](../app-backend/scripts/README.md) | 诊断、查询与显式重置操作 |

## 规划与本地资料

[多立绘与 CHARX 待办](plans/CHARACTER_PORTRAITS_PLAN.md) 保留当前基线、样本研究与未完成事项。计划中的能力不能当作已实现接口；当前行为查对应功能说明与代码。

[聊天 Store 生命周期评估](plans/CHAT_LIFECYCLE_REVIEW.md) 保留初评证据，标注已完成的异步回写、编辑反馈与切服失效修复；进一步拆分 Store 仍待评估。

`local/` 是 Git 忽略的个人草稿、第三方参考与本地验收报告，不作为项目实现或接口契约的权威来源。

## 目录与维护归属

```text
docs/
├── README.md       # 文档总入口
├── guides/         # 任务导读与上手路线
├── architecture/   # 模块职责、调用链与依赖边界
├── features/       # 已实现功能、业务规则与兼容边界
├── api/            # 按领域维护的 HTTP 契约与接口校验说明
├── development/    # 开发流程与持续集成
├── testing/        # 专项验收方法与质量判断
├── plans/          # 未完成规划、研究与待验收事项
├── changelog/      # 按月保存的完整更新记录
└── local/          # 本地草稿与报告（Git 忽略）
```

根目录保留 `README.md`、`AGENTS.md`、`API_TABLE.md` 和 `CHANGELOG.md`。安装、启动、测试与维护命令留在各组件或工具旁边，避免复制后出现多个版本。

新增文档按用途归类并在本页登记，链接使用相对路径。移动文档时同时更新 Markdown 链接、协作说明和目录树中的路径。实现完成后将稳定规则写入功能或接口文档，规划页只保留仍有用的背景与待办；历史变更按月写入 `changelog/YYYY-MM.md`，根更新日志仅保留有限摘要与归档索引。月度文件由该索引统一导航。

本次于 2026-10-26 整理文档分类与代码入口，未逐项重新验收所有业务功能。接口改动更新 `API_TABLE.md` 的索引与 `api/` 对应详情；涉及记忆筛选、统计或继承时同步更新 `api/MEMORY_API.md`。
