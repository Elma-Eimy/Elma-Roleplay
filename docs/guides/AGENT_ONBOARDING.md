# Agent 上手指南

本项目是单用户私有化部署的 AI 角色扮演应用。前后端共用根目录 Git 仓库，运行命令在组件目录执行。先读 [AGENTS.md](../../AGENTS.md) 的执行约定，再按任务阅读下表，无需在开工前通读全部文档。

## 阅读顺序与资料用途

1. 阅读 [项目概览](../../README.md)，确认涉及的产品功能与平台。
2. 查 [后端架构](../architecture/BACKEND.md) 或 [前端架构](../architecture/FRONTEND.md)，定位模块边界。
3. 从下表找到代码与测试，沿调用方阅读实现；涉及接口时对照 [API 总表](../../API_TABLE.md)。
4. 按 [后端测试指南](../../app-backend/tests/README.md) 或 [前端回归检查](../../app-frontend/tests/README.md) 验证，交付时说明实际执行结果。

业务说明集中在 [features/](../README.md#当前功能与业务规则)，接口补充在 `api/`。`plans/` 含待办和研究，更新日志记录历史；二者不能代替当前实现。`local/` 中的个人资料和外部规范副本也不是项目契约。

## 按任务定位

下表代码路径相对仓库根目录，后端测试路径相对 `app-backend/tests/`，前端测试路径相对 `app-frontend/tests/`。测试列给出阅读起点，实际验证范围仍按改动影响确定。

| 任务 | 代码入口 | 测试起点 | 补充阅读 |
| --- | --- | --- | --- |
| 启动、鉴权、生命周期 | `app-backend/application/factory.py`、`lifecycle.py`、`core/` | 后端 `api/test_application.py`、`core/test_migration_logging.py` | [后端架构](../architecture/BACKEND.md) |
| 聊天、Prompt、失败清理 | `app-backend/routers/chat.py`、`services/conversation/chat_turn_service.py`、`chat_engine.py`、`context_assembler.py`、`prompt_compiler.py` | 后端 `conversation/test_chat_turn_service.py`、`test_character_prompt_compatibility.py`、`test_stream_background_persistence.py` | [后端说明](../../app-backend/README.md) 中的 Prompt 规则 |
| 分支、消息、候选切换 | `app-backend/services/conversation/session_service.py`、`message_service.py`；`app-frontend/src/store/chatStore.ts`、`api/messages.ts` | 后端 `conversation/test_branch_context_boundary.py`；前端 `session-api.test.cjs`、`session-lifecycle.test.cjs` | [API 总表](../../API_TABLE.md) |
| SSE、取消与 App 桥接 | `app-frontend/src/api/chat.ts`、`chatStream.ts`、`transports/appStream.ts`、`utils/chatStreamProtocol.ts`、`components/chat/ChatStreamBridge.vue` | 前端 `stream.test.cjs`、`app-stream.test.cjs`、`session-lifecycle.test.cjs` | [前端架构](../architecture/FRONTEND.md) |
| 记忆提取、事件与重试 | `app-backend/services/memory/memory_extraction_service.py`、`memory_extraction_jobs.py`、`memory_event_buffer.py`、`memory_retry_worker.py` | 后端 `memory/test_memory_extraction_jobs.py`、`test_memory_event_buffer.py`、`test_event_retention.py` | [进行中事件](../features/MEMORY_EVENTS.md) |
| 记忆列表、整理与撤销 | `app-backend/services/memory/session_memory_query_service.py`、`memory_consolidation_service.py`、`memory_visibility.py`；`app-frontend/src/composables/useMemoryConsolidation.ts` | 后端 `memory/test_memory_consolidation.py`；前端 `memory-consolidation.test.cjs` | [记忆 API](../api/MEMORY_API.md)、[质量验收](../testing/MEMORY_QUALITY.md) |
| 图谱与联合召回 | `app-backend/services/memory/joint_retrieval.py`、`graph_service.py`、`graph_evidence.py`、`memory_facts.py` | 后端 `memory/test_joint_retrieval.py`、`test_graph_memory_consistency.py` | [图谱与记忆一致性](../features/GRAPH_MEMORY_CONSISTENCY.md) |
| 角色卡、翻译、CHARX 与立绘 | `app-backend/services/character_service.py`、`character_translation_service.py`、`services/media/`；`app-frontend/src/composables/useCharxImport.ts` | 后端 `parsing/`、`conversation/test_character_portraits.py`；前端 `character-card.test.cjs`、`character-translation.test.cjs`、`charx.test.cjs`、`portraits.test.cjs` | [角色卡说明](../features/CHARACTER_CARDS.md) |
| 当前角色状态 | `app-backend/services/conversation/role_state_service.py`；`app-frontend/src/composables/useRoleState.ts` | 后端 `conversation/test_role_state.py`；前端 `role-state.test.cjs` | [角色状态](../features/ROLE_STATE.md) |
| 模型与世界书 | `app-backend/services/infrastructure/model_capabilities.py`、`services/lorebook/`；`app-frontend/src/pages/settings/` | 后端 `conversation/test_model_selection.py`、`lorebook/test_lorebook_trigger_compatibility.py`；前端 `generation-settings.test.cjs` | [模型设置](../features/MODEL_SELECTION.md)、[后端说明](../../app-backend/README.md) |
| TTS、向量同步与资源回收 | `app-backend/services/tts_service.py`、`services/media/audio_service.py`、`services/infrastructure/outbox_worker.py` | 后端 `tts/`、`infrastructure/test_audio_files.py`、`test_avatar_cleanup.py`、`test_vector_outbox_consistency.py` | [后端架构](../architecture/BACKEND.md)、[API 总表](../../API_TABLE.md) |
| 页面与共享 UI | `app-frontend/src/pages/`、`components/`、`App.vue`、`uni.scss` | 前端现有相关测试、类型检查与受影响平台构建 | [前端架构](../architecture/FRONTEND.md) |

## 开工与收尾

开工先检查 `git status --short`，保留已有改动。接口调整同时阅读后端路由与 `schemas.py`、前端领域 API、类型及调用方；数据库结构调整同时核对 `core/models.py` 和 Alembic 迁移链。

后端默认用 `python -m tests` 的隔离入口，不直接对开发库运行测试或维护脚本。前端逻辑变更运行 `npm test` 与 `npm run type-check`。更详细的分组命令、全量回归触发条件和跨端构建要求以 [协作约定](../../AGENTS.md#常用命令与验证) 为准。

完成后同步功能说明、接口契约与当月 `docs/changelog/YYYY-MM.md`，并更新根 [更新日志](../../CHANGELOG.md) 的近期摘要（最多 10 条）；新增文档登记到 [文档导航](../README.md)，月度记录只需登记在更新日志索引。交付说明改动效果、验证结果和未验收范围，尤其区分离线回归、构建通过与真实模型或真机验收。
