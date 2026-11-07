# 群聊创建与管理 API

[API 总表](../../API_TABLE.md) · [文档导航](../README.md)

当前提供固定 2–3 个 AI 成员的管理、后台整轮生成、候选操作和请求恢复查询，全部沿用 `X-API-Key` 鉴权。群聊接口拒绝单聊 ID，旧单聊接口拒绝群聊 ID，均返回 409。没有成员增删或手动选发言者接口。`can_generate` 为运行权可用且正在接收任务的布尔值，Mock 固定 false；M4-D 详情页已接入相应交互。

群聊路径与请求中的资源 ID（含成员角色及来源单聊 ID）范围为 1–9223372036854775807；版本及 offset 范围为 0–9223372036854775807，limit 和 max_steps 继续使用各自更小的上限。超范围参数在资源加载或 SQL 绑定前返回 422，不派发模型、不消费请求 UUID、不确认上一轮。范围内但不存在的 ID 仍返回 404；合法的大 offset 返回空页。

## 创建

`POST /group-sessions` 返回新建群聊详情，状态码 200。数组顺序成为稳定的 slot 1–3，同一角色卡不能重复加入。标题和昵称为 1–50 字（默认“新的群聊”和“用户”），首尾空白移除；共同设定最多 20000 字，空白归一为 null。请求及嵌套模型拒绝未知字段。

<!-- request-example: POST /group-sessions -->
```json
{
  "title": "酒馆会面",
  "user_nickname": "旅人",
  "shared_setting": "众人在边境酒馆初次相遇",
  "members": [
    {"character_id": 11, "origin": {"mode": "card"}},
    {"character_id": 22, "origin": {"mode": "single_snapshot", "session_id": 120}}
  ]
}
```

`card` 从原卡起步，不能指定非空来源 ID；不插入开场消息。`single_snapshot` 必须指定同角色的单聊来源，导入创建时当前已保存状态与记忆，不支持任意历史时点。来源正在处理时返回 409；所有成员和快照在同一事务提交，失败整体回滚。

快照包括当前 active 候选的状态和已保存认知；记忆只复制有效视图中可见且未被隐藏的卡，当前未确认的本地消息来源被排除，祖先遵守分叉边界，手动无来源卡与有效整理摘要保留。来源后续改写、删除或撤销整理不改变快照。新候选生成发言时按个人话题匹配入群快照和本群已确认的新卡，最多三张，发送下一条用户消息确认本轮时，服务端为采用候选中的知情成员登记异步提纯；请求重放沿用同一回执与任务。群内新卡保存在服务端。提纯产生的个人认识和关系印象进入该成员后续新建候选的角色输入，成员详情中的状态仍表示入群起点。

创建没有持久幂等请求 ID。超时或断连不能自动重发 POST；已派发的数据库操作可能完成提交。客户端应先查询群聊列表确认结果。

## 列表与详情

`GET /group-sessions?limit=20&offset=0`：limit 为 1–100，offset 非负，按 updated_at、id 倒序稳定分页。返回 `{sessions, total, limit, offset, has_more}`，每群只出现一次，不含记忆正文。旧 `/sessions` 列表和角色记忆导航均排除群聊。

`GET /group-sessions/{session_id}` 返回单个群聊。列表中的元素和详情结构相同：

```json
{
  "kind": "group",
  "session_id": 201,
  "title": "酒馆会面",
  "user_nickname": "旅人",
  "shared_setting": "众人在边境酒馆初次相遇",
  "created_at": "2026-11-04T10:00:00",
  "updated_at": "2026-11-04T10:00:00",
  "can_generate": false,
  "members": [
    {
      "persona_id": 301,
      "slot": 1,
      "character": {"id": 11, "name": "角色 A", "avatar_path": null},
      "state": {
        "affection_score": 0,
        "current_mood": null,
        "cognition_state": null,
        "current_scenario_override": null,
        "role_state": {},
        "portrait_base": 0
      },
      "origin": {
        "mode": "card",
        "snapshot_version": 1,
        "captured_at": "2026-11-04T10:00:00",
        "source_session_id": null,
        "source_persona_id": null,
        "inherited_memory_count": 0
      }
    }
  ]
}
```

上例仅展示一名成员的字段，实际创建要求 2–3 名成员。Persona ID 是稳定成员标识，不能使用昵称或 slot 代替身份。来源 ID 仅作审计，不表示来源当前仍存在；角色卡本身仍可编辑，冻结的是人格起点与继承事实。

## 只读轮次历史

`GET /group-sessions/{session_id}/rounds?limit=20&offset=0`：limit 为 1–100，offset 非负，按 round_index 倒序分页。返回 `{rounds, total, limit, offset, has_more}`，每个元素包含 round_id、round_index、candidate_id、status、confirmed、revision、finish_reason、error_code、user_content、created_at 和 utterances。status 为 generating、awaiting_confirmation 或 failed；confirmed 独立表示是否已确认。

revision 为所选候选的持久化版本；finish_reason 为正常停止的 wait_user、no_visible_basis、step_limit 或 null，error_code 为失败时的非敏感错误码或 null。旧 v1 候选可没有正常停止原因，前端以已有 status 展示；候选缺失时 revision/finish_reason/error_code 返回 null。不返回导演审计 JSON。

utterances 按轮内 sequence 正序，每项为 `{item_id, sequence, speaker_persona_id, speaker_name, content, created_at}`。仅返回各轮所选候选，用户原文只在 user_content 出现一次；失败候选保留已经提交的前缀。分页以整轮为单位，不截断单轮发言。reasoning、导演理由、知情行和内部状态增量不进入响应。

此接口面向故事操作者，能够读取故事中保存的完整正文，包括角色间的私密内容；不能把该响应作为任何角色的个人上下文。角色生成仍使用后端按成员过滤的独立查询。不存在的群聊返回 404，单聊目标返回 409，分页参数错误返回 422，鉴权沿用 X-API-Key。

普通轮次列表排除撤回记录，但编号不复用。响应新增 `can_generate` 和 `current`，后者在同一读快照返回 group_revision、latest、active_operation 与 capabilities；不会改变选择、确认或运行期限。详情及列表摘要也返回独立的 group_revision，不能以候选 revision 代替它。离线 Mock 只读取虚构轮次样本，不模拟生成或知情判断。

## 接受与候选操作

全部写请求拒绝未知字段。client_request_id 为客户端在提交前生成的 UUID；expected_group_revision 为会话版本。observed_round_id、observed_candidate_id、observed_candidate_revision 为上次读取的 current.latest，首轮发送时全部为空；后续三者必须同时提供。操作路径的 round_id 必须与所见轮次一致，候选必须属于该群该轮。以下示例 ID 仅说明结构。

`POST /group-sessions/{session_id}/rounds` 接受原文（1–20000 个码点，保留首尾空白但拒绝纯空白）。可选 model、thinking_mode（inherit/enabled/disabled）、reasoning_effort，以及 max_steps（默认 4，1–6）。只有新消息与回执一起提交才确认上一成功轮次，后续生成失败不解冻上一轮。

<!-- request-example: POST /group-sessions/{session_id}/rounds -->
```json
{"client_request_id":"00000000-0000-4000-8000-000000000001","expected_group_revision":0,"observed_round_id":null,"observed_candidate_id":null,"observed_candidate_revision":null,"user_content":"  大家好。  ","thinking_mode":"inherit","max_steps":4}
```

`POST /group-sessions/{session_id}/rounds/{round_id}/regenerate` 使用已保存的原文创建新候选，不允许重传原文；可带相同生成选项。新候选完整成功后才切换选择，失败保留旧选择。

<!-- request-example: POST /group-sessions/{session_id}/rounds/{round_id}/regenerate -->
```json
{"client_request_id":"00000000-0000-4000-8000-000000000002","expected_group_revision":2,"observed_round_id":301,"observed_candidate_id":401,"observed_candidate_revision":5,"max_steps":4}
```

`POST /group-sessions/{session_id}/rounds/{round_id}/resume` 显式续接 target_candidate_id/target_candidate_revision 对应的失败候选，沿用冻结参数，不接收新的生成选项；损坏前缀、缺快照或切服时拒绝。`POST /group-sessions/{session_id}/rounds/{round_id}/select-candidate` 只选择同轮成功候选；两者使用以下结构，实际请求各用不同 UUID。

<!-- request-example: POST /group-sessions/{session_id}/rounds/{round_id}/resume; POST /group-sessions/{session_id}/rounds/{round_id}/select-candidate -->
```json
{"client_request_id":"00000000-0000-4000-8000-000000000003","expected_group_revision":4,"observed_round_id":301,"observed_candidate_id":401,"observed_candidate_revision":5,"target_candidate_id":402,"target_candidate_revision":3}
```

`POST /group-sessions/{session_id}/rounds/{round_id}/discard` 只撤回最新未确认轮次，保留原文、候选及回执，不撤销更早确认。

<!-- request-example: POST /group-sessions/{session_id}/rounds/{round_id}/discard -->
```json
{"client_request_id":"00000000-0000-4000-8000-000000000004","expected_group_revision":4,"observed_round_id":301,"observed_candidate_id":401,"observed_candidate_revision":5}
```

send/regenerate/resume 返回 202，select/discard 返回 200，结构为 `{operation_id, request_id, kind, status, accepted}`。status 为 queued/running/succeeded/failed；accepted 保存接受时的 `{round_id, candidate_id, group_revision, candidate_revision, kind}`，不能用旧回执覆盖当前选择。相同 UUID 与规范化请求优先返回原回执；换动作、正文、目标、路径轮次或版本返回 409。省略的思考选项与 inherit 等价，正文仍逐字参与指纹。

同会话存在活动生成时，只接受读取或已接受请求的重放，不接受新的发送、重生成、续接、选择、撤回或删除。HTTP 断连不取消已接受任务。不要通过自动重发聊天 POST 恢复结果；网络错误和 404 也不能证明请求未被接受，应保留原 UUID 继续查询。手动重试提交必须使用原 UUID 和原请求。

新候选在后台对当前阶段的 `invalid_output` 最多调用三次（含首次），覆盖非法 JSON、缺字段及字段校验失败；不重新发送 HTTP 请求或重跑已保存的发言。重试附带格式纠正要求，每次调用均在派发前扣除持久额度，共享原有整轮期限。超时、网络错误、输出截断、取消和语义审查拒绝不走此重试。三次仍失败时保留检查点供显式续接。策略随候选冻结，旧快照没有该策略时保持一次调用；显式重生成使用新策略。

设本次剩余成功发言上限为 K，有界格式重试的调用上限为 `3 × (3K + 1)`，早期策略为 `3K + 1`；不代表必定用完额度。仅需最终提交的续接仍为零次模型调用。重试会延长等待并增加实际模型费用，达到原有时间或调用上限时立即停止。

新候选另冻结亲历审查策略，在角色发言保存前独立核对本人可见依据。`unsupported_experience` 只在角色生成层触发有界重写；无效审查最多三次后以 `experience_check_failed` 停止，不反复改判。通常每个发言增加一次审查调用，该策略每次操作额度为 `output_attempts × (4K+1)`，仍共用原期限。旧候选缺字段时不追溯启用，显式重生成使用新策略；HTTP 请求格式与 GET 恢复规则不变。

新候选可按服务器冻结的回合策略，对推进请求、承接依据和角色发言进行内部校验，不改变以上请求结构。`invalid_basis` 表示导演返回了不可用的承接依据，`agency_conflict` 或 `unsupported_history` 表示提交前审查发现明确冲突；生成仍以 failed 结束，未通过的发言及状态不会提交，已保存前缀保留。是否提供显式续接仍以 can_resume 为准，续接不跳过原审查，也不通过重复发送原聊天恢复。以上为固定错误码，不包含原始模型解释；前端错误字段保持字符串，Mock 仍不模拟真实生成规则。

## 请求与候选查询

`GET /group-sessions/{session_id}/requests/{client_request_id}` 返回回执的 operation_id、request_id、kind、status、revision、round_id、candidate_id、call_count、call_limit、created_at、started_at、deadline_at、finished_at、error_code，以及 accepted、round、candidate、current、can_generate。revision 属于本次操作，candidate.revision 属于候选，current.group_revision 属于会话。查询不会派发模型、增加额度或延长期限。未找到请求返回 404，可能仍在接受事务中；撤回后仍能查询原回执。

`GET /group-sessions/{session_id}/rounds/{round_id}/candidates?limit=20&offset=0` 按 version 倒序分页（limit 1–100，offset 非负），返回 `{round, candidates, current, can_generate, total, limit, offset, has_more}`。round 包含 round_id、round_index、user_content、selected_candidate_id、confirmed、discarded_at、created_at。候选元数据包含 candidate_id、version、revision、status、checkpoint、protocol_version、selected、finish_reason、error_code、can_select、can_resume。

`GET /group-sessions/{session_id}/rounds/{round_id}/candidates/{candidate_id}` 返回 `{round, candidate, current, can_generate, utterances, state_preview}`。utterances 结构同轮次历史；state_preview 明确携带 candidate_id 和成员的 persona_id、role_state、affection_score、current_mood，只表示该候选自身前缀的投影，不写入或替换 members[].state 起点。失败或未选中的候选也可查看，已确认/撤回轮次不可再操作。

current 为 `{group_revision, latest, active_operation, capabilities}`。latest 为空或 `{round_id, candidate_id, candidate_revision, confirmed}`，active_operation 为空或当前活动回执摘要；capabilities 为 can_send、can_regenerate、can_select、can_discard。生成服务不可用时 can_generate、can_send、can_regenerate 和候选 can_resume 为 false；短事务选择和撤回仍按当前状态判断。候选 can_resume 同时核对可靠前缀与提供方，旧失败候选不会伪造参数。以上 GET 均不返回调用参数、凭据、Prompt、reasoning、导演审计、知情行或原始状态增量。

候选详情的 `state_preview.members` 每项包含 `persona_id`、`affection_score`、`current_mood`、`role_state`，并提供入群时的 `cognition_state`（文本或 null）及该候选可用的 `insights` 数组。每条认识为 `{kind, content, target_persona_id, target_name}`：kind 为 cognition/user/member，分别表示个人认识、对用户的看法和对指定成员的看法；仅 member 类型的目标字段有值。接口不返回原始证据引文或内部 ref。

好感、心情和角色状态按此前已确认所选轮次及目标候选的已保存发言重放，失败候选仅反映保存前缀。`insights` 与实际角色输入使用同一成员投影，受该候选冻结的结果上界、此前已确认所选轮次和成员归属约束；迟到提纯不回填旧候选，返回空数组也不表示所有后台任务都已完成。入群认知是起点，群内成长由 insights 单独表示。此查询面向操作者，不应将所有成员的认识拼接到单个角色输入中。

详情页的“当前采用状态”复用此 GET，只有返回的群版本、最新采用轮次、候选及候选 revision 与本页所见一致时显示；查看其他候选不覆盖该面板。无采用候选时引导查看入群起点，旧服务器缺少新字段时明确提示资料不可用，不从其他候选或本机缓存补出成长结果。Mock 继续明确拒绝候选操作与查询。

Mock 对这些新写操作、请求和候选查询明确报“不支持”，不伪造接受或恢复成功；旧管理和虚构轮次只读行为保留。

## 成员立绘

`GET /group-sessions/{session_id}/portraits` 返回 `{session_id, current, can_update, members}`。current 与轮次查询使用相同的版本快照；members 每项为 `{persona_id, portrait_id, image_path}`，无可用立绘时 portrait_id 为 null，image_path 回退角色头像。can_update 只在没有活动任务、没有正在生成的采用候选，且尚无轮次或最新采用轮次未确认时为 true；查看历史候选不授予修改权限。

`PUT /group-sessions/{session_id}/members/{persona_id}/portrait` 在会话锁和短写事务内修改一个成员的选择。portrait_id 必须显式给出：正整数引用该成员角色的现有立绘，null 表示头像。群版本与所见轮次、候选、revision 必须匹配；后三项同时为空或同时提供。不能使用单聊立绘选择接口操作群聊。

<!-- request-example: PUT /group-sessions/{session_id}/members/{persona_id}/portrait -->
```json
{
  "portrait_id": null,
  "expected_group_revision": 0,
  "observed_round_id": null,
  "observed_candidate_id": null,
  "observed_candidate_revision": null
}
```

成功返回 `{session_id, persona_id, portrait_id, group_revision}`。成员不属于本群返回 404，跨角色或已删除的立绘返回 422，版本变化、活动任务或已确认轮次返回 409。PUT 不派发模型，不包含 client_request_id；提交结果不确定时通过 GET 重新核对，不自动重发。相同旧版本重复 PUT 会被拒绝，不再次修改选择。

没有轮次时选择保存为群内成员的可变起步选择，不改写不可变的来源快照。新发送与整轮重生成冻结当前采用的全员选择到新候选；重生成失败保留原采用候选，显式续接沿用失败候选自己的快照。修改最新未确认采用候选只改变该候选，并递增群版本与候选 revision。切换候选恢复各自选择，撤回回到此前采用轮次，全部撤回后回到群内起步选择。

旧候选缺少立绘快照时使用不可变入群资料中的 portrait_base，不读取后来修改的起步选择。素材删除或归属不符时回退头像，不删除候选或改写原快照。轮次列表新增 portraits 数组，候选 state_preview.members 每项新增 portrait 对象，形状均与上述成员项相同；未升级服务器缺少这些字段时前端沿用头像。资源上传和管理继续使用角色立绘接口，Mock 明确拒绝群聊立绘查询和修改。

## 删除与错误

`POST /group-sessions/{session_id}/delete` 删除整个群聊，使用 POST 兼容移动端代理。无需 JSON 请求体，返回：

```json
{"deleted_session_id": 201, "members_deleted": 2, "local_memories_deleted": 0}
```

全部成员、快照和本地数据与 Outbox 清理登记同进同退。只回收本群向量与未被其他故事引用的音频，不修改来源单聊或角色素材。相关故事持锁时返回 409。被群聊引用的角色不能直接删除，须先处理群聊。

| 状态码 | 条件 |
| --- | --- |
| 403 | 缺失或错误的访问密钥 |
| 404 | 资源不存在，或轮次/候选/请求不属于路径群聊及轮次 |
| 409 | 类型不符、忙碌、版本过期、UUID 冲突，或目标状态不允许操作 |
| 422 | 请求结构、成员数、重复角色、文本长度或来源角色不匹配 |
| 503 | 生成运行权不可用；不表示此前已接受的请求可以重新创建 |

离线 Mock 只支持原卡起步的创建、列表、详情和删除；单聊来源快照明确报错，不伪造导入成功。Mock 不代表完整的并发、持久快照和资源回收规则。
