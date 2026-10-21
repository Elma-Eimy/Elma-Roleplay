# 模型与思考设置

聊天模型、是否思考与思考强度分别选择。DeepSeek Flash 和 Pro 均可开启或关闭思考，切换思考不会切换模型。

## 使用方式

- 「设置 → 模型与引擎」配置全局默认模型、思考模式及强度；模型目录可添加服务端支持的模型 ID、显示名称与适配类型。全部模型沿用同一个聊天连接。
- 聊天输入区的模型按钮和侧栏可覆盖当前故事的设置。默认跟随全局；发送和重新生成使用相同选择。
- 故事覆盖保存在当前客户端，按服务器地址和故事 ID 隔离。切换故事恢复设置；新分支复制父故事设置后独立保存；删除故事清理对应设置。这些覆盖不跨设备同步。
- 记忆提取与认知更新共用记忆模型策略；语音文本整理使用独立策略。均不跟随聊天中的模型切换。
- 角色卡阅读翻译使用独立的 `translation_model`，默认 `deepseek-flash`，可在辅助任务模型中选择。支持关闭思考的模型默认非思考，固定推理模型开启思考；不随聊天的思考模式变化。已有中文副本保留，重新翻译才使用新模型。详见 [双版本阅读](CHARACTER_CARDS.md#原文与中文阅读版本)。

## 能力与参数

| 适配类型 | 思考模式 | 强度 | 采样参数 |
| --- | --- | --- | --- |
| `compatible` 普通兼容 | 关闭 | 无 | 温度、Top P、频率与存在惩罚；非默认重复惩罚通过扩展参数传递 |
| `deepseek` DeepSeek 兼容 | 可开关 | low / high / max | 思考时不发送温度、频率与存在惩罚；Flash 思考时 Top P 限制在 0.95–1，普通模式固定 1；Pro 思考时不发送 Top P |
| `reasoning` 固定推理 | 始终开启 | low / medium / high | 不发送普通采样参数 |

能力优先取显式模型目录配置，其次根据 DeepSeek 与 o1/o3/o4 ID 推断；普通名称包含 `pro` 不再被视为思考模型。第三方服务应根据实际参数协议选择适配类型。目录由本地配置生成，不向供应商查询模型。

DeepSeek 强度兼容转换：minimal → low，medium/xhigh → high，ultra → max。不支持的组合在保存配置或用户消息之前返回 400。

## 配置与兼容

`llm.default_chat_model` 是独立默认模型，`reasoning_mode` 只控制默认思考开关。`model_profiles` 是 `{id,label,adapter}` 数组。全局 `reasoning_effort: null` 使用供应商默认强度。

辅助任务字段为 `memory_model`、`memory_thinking_mode`、`memory_reasoning_effort`，以及 `tts_preprocess_model`、`tts_thinking_mode`、`tts_reasoning_effort`。辅助思考开关使用 enabled/disabled。

旧配置首次加载会根据旧思考开关选中的模型槽填入并保存 `default_chat_model`，保持当前模型。旧 `chat_model` / `non_reasoning_chat_model` 保留给只传 `use_reasoning` 的客户端；新客户端使用 `model` / `thinking_mode`。没有显式 TTS 模型时，沿用旧非思考模型作为初始值。

接口见 [HTTP API](../API_TABLE.md)。参数依据 [DeepSeek 思考模式文档](https://api-docs.deepseek.com/guides/thinking_mode/)。
