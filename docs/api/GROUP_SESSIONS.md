# 群聊创建与管理 API

[API 总表](../../API_TABLE.md) · [文档导航](../README.md)

当前提供固定 2–3 个 AI 成员的创建、列表、详情、只读轮次历史和整群删除，全部沿用 `X-API-Key` 鉴权。群聊接口拒绝单聊 ID，旧单聊接口拒绝群聊 ID，均返回 409。当前没有群聊发送、生成、候选切换或成员增删接口；响应固定 `can_generate=false`。

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

快照包括当前 active 候选的状态和已保存认知；记忆只复制有效视图中可见且未被隐藏的卡，当前未确认的本地消息来源被排除，祖先遵守分叉边界，手动无来源卡与有效整理摘要保留。来源后续改写、删除或撤销整理不改变快照。继承快照尚未进入群聊检索或记忆提取。

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

`GET /group-sessions/{session_id}/rounds?limit=20&offset=0`：limit 为 1–100，offset 非负，按 round_index 倒序分页。返回 `{rounds, total, limit, offset, has_more}`，每个元素包含 round_id、round_index、candidate_id、status、confirmed、user_content、created_at 和 utterances。status 为 generating、awaiting_confirmation 或 failed；confirmed 独立表示是否已确认。

utterances 按轮内 sequence 正序，每项为 `{item_id, sequence, speaker_persona_id, speaker_name, content, created_at}`。仅返回各轮所选候选，用户原文只在 user_content 出现一次；失败候选保留已经提交的前缀。分页以整轮为单位，不截断单轮发言。reasoning、导演理由、知情行和内部状态增量不进入响应。

此接口面向故事操作者，能够读取故事中保存的完整正文，包括角色间的私密内容；不能把该响应作为任何角色的个人上下文。角色生成仍使用后端按成员过滤的独立查询。不存在的群聊返回 404，单聊目标返回 409，分页参数错误返回 422，鉴权沿用 X-API-Key。

当前仅开放只读展示，没有群聊生成、手动选角色、确认、候选切换或恢复接口；`can_generate=false` 继续保留。离线 Mock 只读取虚构轮次样本，不模拟生成或知情判断。

## 删除与错误

`POST /group-sessions/{session_id}/delete` 删除整个群聊，使用 POST 兼容移动端代理。无需 JSON 请求体，返回：

```json
{"deleted_session_id": 201, "members_deleted": 2, "local_memories_deleted": 0}
```

全部成员、快照和本地数据与 Outbox 清理登记同进同退。只回收本群向量与未被其他故事引用的音频，不修改来源单聊或角色素材。相关故事持锁时返回 409。被群聊引用的角色不能直接删除，须先处理群聊。

| 状态码 | 条件 |
| --- | --- |
| 403 | 缺失或错误的访问密钥 |
| 404 | 角色、来源单聊、来源人格或目标群聊不存在 |
| 409 | 单聊/群聊类型不符，或相关故事正在处理 |
| 422 | 请求结构、成员数、重复角色、文本长度或来源角色不匹配 |

离线 Mock 只支持原卡起步的创建、列表、详情和删除；单聊来源快照明确报错，不伪造导入成功。Mock 不代表完整的并发、持久快照和资源回收规则。
