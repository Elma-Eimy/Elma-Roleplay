# 模型与思考设置

日常界面只选择「模型」和「思考」：思考项合并关闭与模型支持的各档强度。DeepSeek Flash 和 Pro 均可开启或关闭思考，切换思考不会切换模型。

## 使用方式

- 「设置 → 模型与引擎」配置全局默认模型、思考模式及强度；模型目录可添加服务端支持的模型 ID、显示名称与适配类型。全部模型沿用同一个聊天连接。
- 聊天输入区的模型按钮和侧栏直接展示当前故事的模型与思考档位，没有「跟随默认」选项。新故事首次加载配置时复制服务器默认值，此后独立保存；全局默认变化只影响之后初始化的故事。发送和重新生成使用相同选择。
- 故事覆盖保存在当前客户端，按服务器地址和故事 ID 隔离。切换故事恢复设置；新分支复制父故事设置后独立保存；删除故事清理对应设置。这些覆盖不跨设备同步。
- 记忆提取与认知更新共用记忆模型策略；语音文本整理使用独立策略。均不跟随聊天中的模型切换。
- 角色卡阅读翻译使用独立的模型、思考模式和强度，可在辅助任务设置中选择，不随聊天切换。已有中文副本保留，重新翻译才使用新配置。详见 [双版本阅读](CHARACTER_CARDS.md#原文与中文阅读版本)。

## 能力与参数

| 适配类型 | 思考模式 | 强度 | 采样参数 |
| --- | --- | --- | --- |
| `compatible` 普通兼容 | 关闭 | 无 | 温度、Top P、频率与存在惩罚；非默认重复惩罚通过扩展参数传递 |
| `deepseek` DeepSeek 兼容 | 可开关 | low / high / max | 思考时不发送温度、频率与存在惩罚；Flash 思考时 Top P 限制在 0.95–1，普通模式固定 1；Pro 思考时不发送 Top P |
| `reasoning` 固定推理 | 始终开启 | low / medium / high | 不发送普通采样参数 |

表中是各适配方式的默认能力；模型目录可用 `thinking` 和 `efforts` 覆盖，分别声明是否支持开关和支持的档位。适配方式负责请求参数编码，不再唯一决定能力。`compatible` 或 `reasoning` 下的可开关模型用 `reasoning_effort: none` 关闭，开启时使用配置档位；只有端点支持这些参数时才能声明此能力。`deepseek` 使用 `extra_body.thinking` 开关。`efforts: []` 表示无需强度参数，前端不冻结虚构档位，后端也不发送请求或全局设置中的强度。

能力优先取显式模型目录配置，其次根据 DeepSeek 与 o1/o3/o4 ID 推断；普通名称包含 `pro` 不被视为思考模型。目录由本地配置生成，不向供应商查询模型；未知模型不会自动获得思考能力。

DeepSeek 强度兼容转换：minimal → low，medium/xhigh → high，ultra → max。只有当前能力列表未直接声明该档位时才转换；不支持的组合在保存配置或用户消息之前返回 400。

## 配置与兼容

`llm.default_chat_model` 是独立默认模型，`chat_thinking_mode` 为 `enabled` 或 `disabled`，`reasoning_effort` 单独选择强度。`model_profiles` 是 `{id,label,adapter,thinking?,efforts?}` 数组；省略能力字段或设为 null 时使用适配方式默认值。

`reasoning_mode` 保留为布尔兼容别名，读取旧文件时只用于初始化缺失的 `chat_thinking_mode`，两者同时存在时新字段优先。HTTP 同时提交相冲突的新旧字段返回 400。新前端只提交新字段。API 保留 `reasoning_effort: null`；通用可开关模型必须有开启档位，未指定强度时选择 high 或列表首档，以明确发送开启参数。新故事仍冻结明确选择，不随全局更新。

旧客户端保存的空模型或 `inherit` 值，在该故事加载服务器配置后一次性解析并保存；已有明确选择保留。首次加载失败时阻止发送，避免使用猜测的默认值。

模型目录按完整 ID 去重，同名且不同 ID 的条目附带 ID 区分，不自动认定为供应商别名或合并。翻译模型不再在缺省配置中额外引入硬编码的 Flash ID；已明确配置的翻译模型继续保留。

辅助任务分别使用 `memory_model/memory_thinking_mode/memory_reasoning_effort`、`tts_preprocess_model/tts_thinking_mode/tts_reasoning_effort`、`translation_model/translation_thinking_mode/translation_reasoning_effort`。思考模式使用 enabled/disabled；空强度不继承聊天强度。固定思考模型沿用始终开启的行为，显式提交关闭返回 400。

旧配置首次加载会根据旧思考开关选中的模型槽填入并保存 `default_chat_model`，保持当前模型。尚无 `chat_thinking_mode` 时，迁移按原先隐式调用实际生效的能力解析模式：未知模型保留关闭思考的行为，固定思考模型保存 enabled。显式请求开启未知模型思考仍会被拒绝。

缺失的记忆、翻译、TTS 模型在迁移时冻结原先的默认值，此后不再从旧槽位回退；固定思考任务的隐式模式归一为 enabled，完整设置读取后可以原样回写，显式关闭仍拒绝。新配置缺失辅助模型时从当前默认聊天模型初始化一次。旧 `chat_model/non_reasoning_chat_model` 仅供只传 `use_reasoning` 的请求兼容，不再加入现代模型目录；新请求使用 `model/thinking_mode`。

保存配置在进程内串行执行：复制候选配置、归一化并校验完整模型组合、在同目录写入临时文件并同步后原子替换，成功后发布运行状态。任何保存失败都返回错误并保留旧状态，读取格式错误的 YAML 会明确失败，不用空配置覆盖。模型调用使用配置快照；群聊已接受候选继续使用原冻结参数，不因全局配置变化重建。

接口见 [HTTP API](../../API_TABLE.md)。参数依据 [DeepSeek 思考模式文档](https://api-docs.deepseek.com/guides/thinking_mode/)。
