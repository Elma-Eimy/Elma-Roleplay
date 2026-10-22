# API 模块约定

请求统一经过 `config.ts`，由它管理服务器地址、认证请求头、错误处理和 Mock 存储。

| 模块 | 职责 | 类型 | 离线实现 |
| --- | --- | --- | --- |
| `sessions.ts` | 创建、列表、分支、详情、标题、删除与认知更新 | `../types/sessions.ts` | `mock/sessions.ts` |
| `roleStates.ts` | 当前角色状态读取和携带版本的增量校正 | `../types/roleState.ts` | 明确提示暂不支持，不伪造成功 |
| `portraits.ts` | 角色多立绘上传、管理与当前剧情节点的手动选择 | `../types/portraits.ts` | 明确提示暂不支持，不伪造成功 |
| `charx.ts` | 有界角色包上传预览、缩略图分页、取消与幂等导入 | `../types/charx.ts` | 明确提示暂不支持，不伪造成功 |
| `messages.ts` | 历史分页、消息编辑/删除与候选切换 | `../types/messages.ts` | `mock/messages.ts` |
| `memories.ts` | 记忆提纯、列表筛选、角色概览、增删改与整理预览/逐组审阅/应用/撤销 | `../types/memories.ts` | `mock/memories.ts`；模型整理与审阅明确不支持 |
| `prompts.ts` | 编译提示词预览与 Token 估算结果 | `../types/prompts.ts` | `mock/prompts.ts` |

`sessions.ts` 为已有调用方保留消息、记忆、提示词函数及相关类型的兼容导出。新增代码直接从对应领域模块导入函数，从 `types/` 导入类型：

```ts
import { getSessionMemories } from "@/api/memories";
import type { MemoryChunk } from "@/types/memories";
```

`api/` 的领域模块负责请求路径、参数与 `USE_MOCK` 分流；`mock/` 只实现本地行为，不发 HTTP 请求。类型模块只依赖类型，不依赖 Store、组件或 Mock。角色记忆概览在离线模式下复用 `mock/sessions.ts` 的分页和 `mock/memories.ts` 的筛选，避免从 Mock 反向调用 HTTP 入口。

此次拆分保留原有 Mock 行为，不将其视为后端所有业务规则的完整实现。接口契约见根目录 [API 总表](../../../API_TABLE.md)，回归范围见 [前端测试说明](../../tests/README.md)。
