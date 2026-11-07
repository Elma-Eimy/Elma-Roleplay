# 项目文档导航

从阅读目的选择入口。开发前先读 [协作约定](../AGENTS.md)，具体代码与测试由 [Agent 上手指南](guides/AGENT_ONBOARDING.md) 定位。

## 按目的阅读

| 你要了解什么 | 阅读入口 |
| --- | --- |
| 产品能力与安装运行 | [项目说明](../README.md)、[后端快速开始](../app-backend/README.md#快速开始)、[前端快速开始](../app-frontend/README.md#快速开始) |
| 模块职责与调用链 | [后端架构](architecture/BACKEND.md)、[前端架构](architecture/FRONTEND.md)、[群聊架构](architecture/GROUP_CHAT.md) |
| 当前功能规则 | 本页的 [功能说明](#当前功能与业务规则)；HTTP 细节查 [API 总表](../API_TABLE.md) |
| 开发、排错与测试 | [Agent 上手指南](guides/AGENT_ONBOARDING.md)、本页的 [验证与维护入口](#开发测试与维护) |
| 群聊实现进度与质量边界 | [群聊实施进度](plans/group-chat/README.md)、[群聊验收索引](testing/group-chat/README.md) |
| 未完成规划与历史变更 | 本页的 [规划入口](#规划与历史)、[更新日志](../CHANGELOG.md) |

## 当前功能与业务规则

| 文档 | 内容 |
| --- | --- |
| [角色卡导入](features/CHARACTER_CARDS.md) | 格式兼容、中文阅读版本、CHARX 导入与资源生命周期 |
| [模型与思考设置](features/MODEL_SELECTION.md) | 默认模型、故事覆盖、辅助任务模型与兼容 |
| [当前角色状态](features/ROLE_STATE.md) | 增量状态、人工校正、候选与分支恢复 |
| [图谱与记忆一致性](features/GRAPH_MEMORY_CONSISTENCY.md) | 共同事实、联合检索、证据、时间与分叉边界 |
| [进行中事件](features/MEMORY_EVENTS.md) | 跨批事件缓冲、阶段保存、长期准入与重试 |
| [群聊功能与业务规则](features/GROUP_CHAT.md) | 成员起点、知情、整轮候选、恢复、成员记忆与当前能力边界 |

Prompt、世界书和 TTS 的部分机制仍在 [后端说明](../app-backend/README.md) 中，记忆查询与整理规则见 [记忆 API](api/MEMORY_API.md)。这里直接指向已有正文，不另建重复说明。

## 接口契约

| 文档 | 内容 |
| --- | --- |
| [HTTP API 总表](../API_TABLE.md) | 前后端共享的路由索引与各领域契约入口 |
| [API 阅读与校验](api/README.md) | 请求、响应、兼容规则导航及隔离校验方法 |
| [群聊 API](api/GROUP_SESSIONS.md) | 创建、来源快照、整轮操作、候选预览与请求恢复 |
| [记忆 API](api/MEMORY_API.md) | 筛选、统计、继承、导航、整理预览与撤销 |
| [前端 API 模块](../app-frontend/src/api/README.md) | 领域请求封装、共享类型、兼容导出与 Mock 边界 |

## 开发、测试与维护

| 文档 | 内容 |
| --- | --- |
| [项目协作约定](../AGENTS.md) | 模块边界、核心行为约束、数据隔离与验证要求 |
| [Agent 上手指南](guides/AGENT_ONBOARDING.md) | 按任务查前后端代码入口与回归测试 |
| [后端说明](../app-backend/README.md) | Python 环境、运行配置、Prompt 规则与启动 |
| [后端配置示例](../app-backend/config.yaml.example) | 不含真实凭据的配置示例 |
| [前端说明](../app-frontend/README.md) | 安装、连接配置、多端开发与构建 |
| [后端测试指南](../app-backend/tests/README.md) | 隔离回归、领域分组与手动场景 |
| [前端回归检查](../app-frontend/tests/README.md) | 离线回归、类型检查与跨端验证 |
| [记忆整理质量验收](testing/MEMORY_QUALITY.md) | 固定样本、隔离回放、显式在线验收与人工审阅 |
| [群聊验收索引](testing/group-chat/README.md) | 最近质量结论、未覆盖项及各阶段报告；报告中的测试数量按对应版本理解 |
| [持续集成](development/CI.md) | CI 环境、文档链接检查、回归范围与失败排查 |
| [后端维护工具](../app-backend/scripts/README.md) | 诊断、查询与显式重置操作 |

## 规划与历史

| 入口 | 维护范围 |
| --- | --- |
| [群聊实施进度](plans/group-chat/README.md) | 最新状态与下一步；统一导航到需求基线、M1–M5 阶段设计和交接历史 |
| [多立绘与 CHARX 待办](plans/CHARACTER_PORTRAITS_PLAN.md) | 当前基线、样本研究与未完成事项 |
| [聊天 Store 生命周期评估](plans/CHAT_LIFECYCLE_REVIEW.md) | 初评证据、已完成修复与待评估的 Store 拆分 |
| [Outbox 向量同步容错与自愈待办](plans/OUTBOX_VECTOR_SELF_HEALING.md) | NULL 文档 ID 重试现象及待实施方案 |
| [更新日志](../CHANGELOG.md) | 最多 10 条近期摘要与月度历史索引 |

群聊模块设计和阶段报告由各自索引维护，总导航不逐项重复进度。近期新增[亲历审查与混合更正回归](testing/group-chat/SOURCE_AND_CORRECTION_CHECKS.md)，区分隔离自动检查与待执行的真实验证。规划记录目标与取舍，报告保存当时的验证证据；当前行为查功能说明与接口契约，不能由旧记录中的“下一步”推断。

## 目录与正文归属

```text
docs/
├── README.md                 # 按阅读目的导航
├── guides/                   # 操作导读与代码、测试定位
├── architecture/             # 当前模块职责、调用链与依赖边界
│   └── GROUP_CHAT.md         # 群聊当前架构
├── features/                 # 当前功能、业务规则与兼容边界
├── api/                      # 各领域 HTTP 契约
├── development/              # 开发流程与持续集成
├── testing/                  # 专项验收方法与证据
│   └── group-chat/           # 验收索引、阶段报告与后续复验
├── plans/                    # 需求、待办与设计背景
│   └── group-chat/           # 实施入口、需求基线、模块设计、交接历史
├── changelog/                # 月度完整更新记录
└── local/                    # 本地草稿、原型与报告（Git 忽略）
```

根 README 保留产品概览与入口，安装、配置、运行和构建步骤由组件 README 维护。架构说明按运行职责组织，功能说明解释当前行为，API 文档维护 HTTP 契约。相同规则只保留一处正文，其他位置链接引用；已有混合正文按实际需要逐项迁移。

新增独立主题在本页登记；群聊模块设计或阶段报告登记到对应索引。移动文件时同步更新所有引用和目录树，新增文档先纳入 Git 跟踪，再运行根目录的 `python tools/check_docs.py`。接口文档变更还需执行后端 API 文档隔离回归。维护与验证要求以 [协作约定](../AGENTS.md) 为准。

## 本地资料

`docs/local/` 保存个人草稿、第三方参考、原型与本地验收材料，不作为当前功能或接口的权威正文。真实群聊测试的本机入口是 `docs/local/group-chat-tests/README.md` 和同目录的 `index.json`，按日期、版本、场景保留原始报告、完整对话与测试库；它们不随 Git 分发。正式验证结论由 [群聊验收索引](testing/group-chat/README.md) 组织。

本轮于 2026-11-07 整理文档分类、入口和过期描述，没有重新验收全部业务功能。
