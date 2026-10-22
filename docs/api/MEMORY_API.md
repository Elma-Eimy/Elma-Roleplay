# 记忆管理与角色记忆导航 API 对齐标准

本文是根目录 [API 总表](../../API_TABLE.md) 的记忆模块补充规范，供前后端共同维护。其他接口请查阅 API 总表。

> 状态：当前实现契约
> 代码核对日期：2026-10-20
> 适用项目：`app-frontend` / `app-backend`

本文档说明记忆管理界面与角色详情记忆导航的当前前后端契约。分页响应和筛选规则已经实现；这里不再保留当时的迁移任务和未来接口设想。

## 1. 设计原则

1. 长期记忆按会话故事线隔离，并沿 Persona 祖先链继承。
2. 记忆是否被替代必须根据当前故事的 Persona 继承链动态判断，不能保存为全局 `is_superseded` 布尔字段。
3. 搜索、分类和替代状态筛选必须在数据库分页之前完成。
4. 记忆管理列表和统计信息以 SQLite 为权威数据源，不使用 ChromaDB 生成管理列表或统计数量。
5. 角色详情页负责故事记忆导航；聊天页负责当前故事的具体记忆管理。
6. 所有分页列表必须使用稳定排序，并由服务端返回 `total` 和 `has_more`。

## 2. 通用数据结构

### 2.1 MemoryItem

```json
{
  "id": 101,
  "content": "用户喜欢雨天和爵士乐。",
  "memory_type": "fact",
  "importance_score": 0.8,
  "is_local": true,
  "created_at": "2026-07-28T10:00:00",
  "origin_session_id": 12,
  "source_start_message_id": 20,
  "source_message_id": 22,
  "supersedes_id": null,
  "is_superseded": false
}
```

| 字段 | 类型 | 可空 | 说明 |
| --- | --- | --- | --- |
| `id` | integer | 否 | 记忆主键 |
| `content` | string | 否 | 记忆正文 |
| `memory_type` | enum | 否 | `event`、`emotion`、`relationship`、`fact` |
| `importance_score` | number | 否 | 原始权重，范围 `0.0~1.0` |
| `is_local` | boolean | 否 | 是否属于当前 Session Persona |
| `created_at` | ISO 8601 string | 是 | 创建时间 |
| `origin_session_id` | integer | 是 | 记忆最初产生的会话 |
| `source_start_message_id` | integer | 是 | 来源消息范围起点 |
| `source_message_id` | integer | 是 | 来源消息范围终点的外键引用；消息删除后可置空 |
| `supersedes_id` | integer | 是 | 当前记忆直接替代的前一版本 |
| `is_superseded` | boolean | 否 | 在当前故事中是否已被版本替代或整理结果收起 |
| `consolidation_id` | integer | 是 | 整理产物所属记录；普通原卡为 null |

### 2.2 MemoryStats

```json
{
  "effective_total": 32,
  "local_active": 24,
  "inherited_active": 8,
  "superseded": 3
}
```

统计口径：

| 字段 | 定义 |
| --- | --- |
| `local_active` | 属于当前 Persona，且在当前继承链中未被替代 |
| `inherited_active` | 属于祖先 Persona，且在当前继承链中未被替代 |
| `effective_total` | `local_active + inherited_active` |
| `superseded` | 当前故事可见、但已被版本替代或已选整理结果收起的原卡（两者取并集） |

## 3. 会话记忆列表

### GET `/sessions/{session_id}/memories`

获取指定故事线可见的记忆。服务端必须先应用继承范围、搜索、分类和替代状态，再执行分页。

### Query Parameters

| 参数 | 类型 | 默认值 | 规则 |
| --- | --- | --- | --- |
| `q` | string | 空 | 记忆正文关键词；最多 200 字符，超出返回 `422` |
| `scope` | enum | `all` | `all`、`local`、`inherited` |
| `status` | enum | `active` | `active`、`superseded`、`all` |
| `limit` | integer | `20` | `1~100` |
| `offset` | integer | `0` | 大于等于 0 |

### Scope 定义

| 值 | 定义 |
| --- | --- |
| `all` | 当前 Persona 与全部祖先 Persona 的可见记忆 |
| `local` | 仅当前 Persona 产生的记忆 |
| `inherited` | 仅祖先 Persona 产生的记忆 |

### Status 定义

| 值 | 定义 |
| --- | --- |
| `active` | 当前继承链中未被替代的有效记忆 |
| `superseded` | 当前故事中已被新版本替代或整理收起的历史原卡 |
| `all` | 有效与已替代记忆 |

### 前端分类映射

| UI 分类 | `scope` | `status` |
| --- | --- | --- |
| 全部 | `all` | `active` |
| 当前故事／此故事 | `local` | `active` |
| 继承 | `inherited` | `active` |
| 历史原卡 | `all` | `superseded` |

### Response `200 OK`

```json
{
  "items": [
    {
      "id": 101,
      "content": "用户喜欢雨天和爵士乐。",
      "memory_type": "fact",
      "importance_score": 0.8,
      "is_local": true,
      "created_at": "2026-07-28T10:00:00",
      "origin_session_id": 12,
      "source_start_message_id": 20,
      "source_message_id": 22,
      "supersedes_id": null,
      "is_superseded": false
    }
  ],
  "total": 32,
  "limit": 20,
  "offset": 0,
  "has_more": true,
  "facets": {
    "effective_total": 32,
    "local_active": 24,
    "inherited_active": 8,
    "superseded": 3
  }
}
```

### 响应字段语义

- `items`：应用 `q + scope + status` 后的当前页数据。
- `total`：应用 `q + scope + status` 后的结果总数。
- `has_more`：`offset + items.length < total`。
- `facets`：应用 `q` 后、应用当前 `scope/status` 前的分类统计。
- 搜索状态下，顶部分类数量应随 `q` 更新。

### 排序

当前使用 offset 分页，采用稳定排序：

```sql
ORDER BY created_at DESC, id DESC
```

新增、删除或更新记忆后，前端应重新请求第一页和 `facets`。

### 错误响应

| HTTP | 场景 |
| --- | --- |
| `404` | Session 或 Persona 不存在 |
| `422` | `scope`、`status`、`limit` 或 `offset` 不合法 |

## 4. 记忆增删改

以下接口路径保持不变：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| `POST` | `/sessions/{session_id}/memories` | 创建当前故事的本地记忆 |
| `PUT` | `/sessions/{session_id}/memories/{memory_id}` | 更新当前故事的本地记忆 |
| `DELETE` | `/sessions/{session_id}/memories/{memory_id}` | 删除当前故事的本地记忆 |

继承记忆继续保持只读：

| HTTP | 场景 |
| --- | --- |
| `403` | 尝试编辑或删除继承记忆 |
| `404` | Session、Persona 或 Memory 不存在 |

创建、更新或删除成功后，前端必须重新加载当前分类第一页，不能只依赖本地数组推算 `total/facets`。

有关联有效整理的来源卡与所有整理产物不允许直接编辑、删除，返回 `409`。应先撤销整理再修改原卡；已有子故事实际可见的整理组仍引用的来源继续只读，避免破坏其整理依据。仅有旧版遗留关联、但因来源边界而不可见的整理组不锁住原卡。同一批中各组按实际可见性分别判断。整理不会修改图谱、认知、消息、好感度或音频。

### 可预览的存量记忆整理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/sessions/{session_id}/memory-consolidations` | 当前故事整理记录，含来源快照、建议和结果；`limit=10`（1–20）、`offset=0`（≥0） |
| POST | `/sessions/{session_id}/memory-consolidations/preview` | 请求 `{ "after_id": 0, "mode": "full" }`，按原卡 ID 升序扫描最多 100 张；支持手动增量模式 |
| POST | `/sessions/{session_id}/memory-consolidations/{batch_id}/apply` | 请求 `{ "group_ids": [0], "expected_revision": 0 }`，应用指定建议 |
| PUT | `/sessions/{session_id}/memory-consolidations/{batch_id}/groups/{group_id}` | 保存单组审阅，返回完整整理记录 |
| POST | `/sessions/{session_id}/memory-consolidations/{batch_id}/undo` | 无请求体，撤销本次整理对当前故事的影响 |

预览只扫描当前 Persona 的有效普通原卡，不含继承卡、已被替代/整理收起的原卡和整理产物。每次模型输入有界；每批最多 12 组、每组 2–12 张、各组来源不重叠、类型相同。仅支持 `duplicate`（重复内容）和 `event`（同一次事件，来源必须全为 event），不处理矛盾、时态变化或不同事件的主题归纳。建议正文 4–500 字符，理由 1–160 字符。模型是否正确保留语义仍需用户审阅。

手动扫描有两个入口：

- `mode=incremental`（检查新增与变更）：只送检当前版本未检查的原卡；包括新增卡和内容、类型、权重、来源范围、替代关系发生变化的旧卡。每次续扫均传 `after_id=0`，不使用高 ID 水位，因此不会漏掉低 ID 旧卡的修改。非零游标返回 `422`。
- `mode=full`（重新检查全部）：忽略已检查标记，从 `after_id` 后依次重新送检，按 `next_after_id` 续扫。省略 mode 时沿用此模式，兼容原客户端。

两个入口均由用户点击触发，无后台定时扫描。增量模式不补入已检查旧卡，两个模式均不做跨批候选发现；新旧卡之间或不同批次之间的重复可能保留。“已检查”与“已审阅/已应用”独立，生成成功但未选择、已忽略或尚未应用的建议仍留在历史中，不因再次点击增量检查而自动重复生成。需要重新判断时可使用全量入口。

至少两张待检卡才调用模型；合法响应即使没有建议也记录为已检查。模型调用、格式/来源校验或预览保存失败都不推进进度。来源在调用期间变化、删除或失效时，该版本不记录为已检查；若它属于归并建议，同组其他来源也不推进本次进度，保留整组重试所需的卡片，其他安全组仍可推进。不清除其他较新成功扫描已经保存的记录。预览仍保留原始送检快照，待检卡可在后续增量中再次送检。只有一张待检卡时不调用模型、不推进检查记录，等待另一张新增/变更卡后再手动检查。

进度表 `memory_consolidation_scans` 按 Persona 和原卡保存成功送检时的版本指纹与时间，不复制到分支，不受应用/撤销影响。统计仅包含当前可整理的有效本地原卡；应用后收起的原卡不计入，撤销恢复原卡后其未变版本仍算已检查。删除故事或原卡会级联删除对应进度。旧库迁移新增空进度表，保留全部原卡及已有预览，不根据旧记录猜测检查进度，升级后第一次增量会从未检查开始。

响应增加 `scan_mode`（旧记录默认 full）、`model_checked`、`recorded_count`。`scanned_count` 为本次取出的原卡数；只有一张时可能取出但未送模型，须结合 `model_checked=false` 与 `recorded_count=0` 阅读。`remaining_count` 为本次开始时请求范围中的原卡总数。全量 `has_more` 表示游标后仍有卡；增量 `has_more` 表示保存时至少还有两张待检卡，继续时不传 ID 游标。

`scan_status` 为当前统计：`{ "eligible_count": 10, "checked_count": 8, "pending_count": 2 }`。GET 历史列表在顶层返回一次统计，单条 POST/PUT 返回中附带统计；历史 items 内不重复计算。它们表示读取时的有效原卡状态，不是历史批次的完成比例，也不代表整个故事已去重。

逐组审阅请求为 `{ "expected_revision": 0, "content": "审阅后的完整正文", "ignored": false, "ignore_reason": "" }`。`expected_revision` 必填且非负；`content` 可省略，提供时去除首尾空白后须为 4–500 字符；`ignored` 默认 false；`ignore_reason` 为可选原因或备注，最多 160 字符。仅待审阅批次可保存；忽略不删除原卡，可在应用前恢复，仅作用于这份预览，不阻止未来重新生成建议。来源过期仍可忽略或恢复，但不能修改正文或应用。

返回新增批次 `review_revision`（旧记录默认为 0）和分组 `original_content`（模型原稿）、`ignored`、`ignore_reason`、`conflict`（无冲突为 null）。预览记录读取时逐组检查来源是否已修改、删除、不再有效及日期/否定边界，界面展示原因并禁止勾选冲突组；其他有效组仍可应用。保存审阅会递增版本；保存与应用版本不匹配返回 `409`，须刷新后重新核对。应用请求的 `expected_revision` 默认 0，兼容未经编辑的旧预览；已忽略组不能应用。客户端编辑期间禁止应用，保存成功清空选择以便重新确认。

审阅与模型原稿保存在既有预览 JSON 中，无表结构变更；不修改来源快照，不生成记忆或向量任务。生成对话期间保存审阅同样返回 `409`。应用后保持批量撤销，不提供单组独立应用/撤销。

整理记录结构：

```json
{
  "id": 1,
  "status": "preview",
  "created_at": "2026-10-20T12:00:00",
  "scanned_count": 2,
  "remaining_count": 2,
  "has_more": false,
  "next_after_id": 102,
  "sources": [{"id": 101, "content": "原卡正文", "memory_type": "event", "importance_score": 0.7, "source_start_message_id": 20, "source_message_id": 22, "supersedes_id": null}],
  "groups": [{"id": 0, "kind": "event", "source_ids": [101, 102], "content": "整理正文", "reason": "同一次事件的互补细节"}],
  "selected_group_ids": [],
  "results": []
}
```

`sources` 实际包含本批全部取出的卡片（示例省略第二张）；`remaining_count` 为本次请求范围的原卡总数。`has_more` 为真时，全量模式传 `next_after_id` 续扫，增量模式传 `after_id=0` 重新查询待检集合。继续检查不会自动应用前一批建议。GET 按 ID 倒序返回 `{ "items": [整理记录], "total": 12, "limit": 10, "offset": 0, "has_more": true, "scan_status": { "eligible_count": 10, "checked_count": 8, "pending_count": 2 } }`；三个 POST 和审阅 PUT 直接返回整理记录。历史分页不会删除旧记录，较早的已应用整理仍可重新打开和撤销。当前按卡片顺序分批，不在批间做语义聚类，因此可能漏掉相距很远的重复卡。

后端会跳过事件来源发生日期明确冲突的整组建议，保留其他安全建议，并重新顺序编号；被跳过组的原卡保持有效，不直接删卡、拼接摘要或自动重试模型。应用时再次检查同一边界，旧预览若包含跨日期事件则返回 `409`，需重新生成预览。预约、计划等句中的目标日期不作为本次发生日；同次就诊中预约未来复诊不因此被拆开。当前日期规则覆盖数字形式的中文年月日、`YYYY-MM-DD`/`YYYY/MM/DD` 及明确年份，不推断相对日期、未注明日期或隐含事件身份，因此仍需审阅建议。

`duplicate` 来源的明确否定标记有差异时也跳过整组，应用旧预览时同样返回 `409`，避免把肯定和否定的独立事实当作重复。该规则是保守筛查：可能让不同措辞的等价事实保持分开，未匹配到否定标记也不能证明两个命题等价。事件组不按这一否定标记规则拆分，以保留同次事件内“用户车坏了、林墨车没坏”等正常细节。

预览会持久化建议和完整来源快照，不创建新记忆或向量任务。应用仅接收分组编号和审阅版本，正文始终来自已保存建议；在 `BEGIN IMMEDIATE` 事务内校验来源内容、类型、权重、消息范围、版本与有效性，再原子写入整理产物、多来源关系、当前故事快照和向量 Outbox。结果权重取来源最大值，来源范围取起止包络，精确依据仍以来源关联/快照为准。

状态为 `preview → applied → undone`；同一份预览只能应用一次，未选组保持原样，想调整选择应重新预览。同分组的重复应用、重复撤销幂等。应用后的原卡仍留在 SQLite 和向量库，并进入“历史原卡”分类。撤销保留整理产物与记录，恢复当前故事原卡；已建立的子故事保持其分叉时快照。整理结果若在当前故事可见范围内已有后续版本，撤销返回 `409`，避免恢复过时信息；仅子故事独有的后续版本不阻止父故事撤销。

分叉复制父故事当时启用且至少有一组在子故事可见的整理记录关联，后续父故事应用/撤销互不传播；既有故事不追溯继承新增整理。任何包含当前分叉消息边界之后来源的结果都不可见，也不屏蔽原卡。正常记忆列表与检索同样过滤祖先的未来来源消息；旧数据缺少可靠分叉边界时不继承具有来源上界的祖先卡。

SQLite 内部字段 `source_message_id_bound` 保存非外键的来源消息上界，不增加 HTTP 响应字段。原消息删除使 `source_message_id` 置空时，上界仍保留，不能将该卡当作手动无来源记忆继承。新整理产物取各原卡持久上界的最大值，即使整理前消息已经删除也不能缩小边界。真正无消息来源的手动卡继续按原规则继承。旧库升级先回填现存消息引用，再利用已有整理预览的来源快照和关联恢复可确定的丢失上界；已经丢失且没有任何快照留存的旧来源无法凭空恢复。

错误：故事或本地记录不存在为 `404`；请求模型不合法为 `422`；来源变化、记录状态冲突、对话生成中应用/撤销为 `409`；模型失败或建议格式/来源不合法为 `502`。失败不改动原卡。预览请求较慢或客户端断连后，可重新查询记录确定是否完成；应用网络异常时也先查询记录，不重新生成整份预览来重试应用。

ChromaDB 只作为索引：召回前用 SQLite 有效 ID 限定查询范围，旧向量不会绕过整理和分支边界；正文与权重仍从 SQLite 命中卡加载。新整理产物经 Outbox 异步建立索引，尚未同步完成期间可能暂时无法召回；撤销无需等待向量删除。离线 Mock 返回空整理记录，并明确拒绝生成、应用和撤销，不模拟在线模型结论。

## 5. 角色记忆导航

### GET `/characters/{character_id}/memory-overview`

角色详情页记忆标签的专用接口。应在用户首次打开记忆标签时懒加载。

### Query Parameters

| 参数 | 类型 | 默认值 | 规则 |
| --- | --- | --- | --- |
| `limit` | integer | `50` | `1~100` |
| `offset` | integer | `0` | 大于等于 0 |

### Response `200 OK`

```json
{
  "character_id": 8,
  "story_count": 4,
  "recent_session_id": 21,
  "sessions": [
    {
      "session_id": 21,
      "title": "雨夜重逢",
      "parent_session_id": 12,
      "created_at": "2026-07-26T18:00:00",
      "updated_at": "2026-07-28T21:30:00",
      "last_message": {
        "content": "我们在车站约定下次见面……",
        "created_at": "2026-07-28T21:30:00"
      },
      "memory_stats": {
        "effective_total": 32,
        "local_active": 24,
        "inherited_active": 8,
        "superseded": 3
      }
    }
  ],
  "total": 4,
  "limit": 50,
  "offset": 0,
  "has_more": false
}
```

### 行为要求

1. `sessions` 按 `updated_at DESC, session_id DESC` 排序。
2. `recent_session_id` 是该角色全部会话中排序后的第一条，不受当前页 `offset` 影响；没有会话时为 `null`。
3. `last_message` 只统计 `is_active = true` 的最后一条消息；没有消息时为 `null`。
4. `last_message.content` 应返回适合预览的完整文本或服务端截断文本，前端负责最终两行省略。
5. `memory_stats` 必须与会话记忆列表复用同一套继承和替代判断。
6. 服务端不得为每个 Session 分别执行完整记忆列表请求。

### 错误响应

| HTTP | 场景 |
| --- | --- |
| `404` | Character 不存在 |
| `422` | 分页参数不合法 |

## 6. 角色会话列表优化

### GET `/sessions`

现有接口继续使用 `character_id` 筛选，增加最后消息与标准分页信息，消除角色详情页逐会话请求历史记录的 N+1 问题。

### Query Parameters

| 参数 | 类型 | 默认值 | 规则 |
| --- | --- | --- | --- |
| `character_id` | integer | 必填 | 角色 ID |
| `include_last_message` | boolean | `true` | 是否返回最后一条有效消息 |
| `limit` | integer | `50` | `1~100` |
| `offset` | integer | `0` | 大于等于 0 |

### Response `200 OK`

```json
{
  "character_id": 8,
  "sessions": [
    {
      "id": 21,
      "title": "雨夜重逢",
      "parent_session_id": 12,
      "fork_message_id": 300,
      "created_at": "2026-07-26T18:00:00",
      "updated_at": "2026-07-28T21:30:00",
      "persona": {
        "id": 42,
        "affection_score": 68,
        "current_mood": "期待"
      },
      "last_message": {
        "content": "我们在车站约定下次见面……",
        "created_at": "2026-07-28T21:30:00"
      }
    }
  ],
  "total": 4,
  "limit": 50,
  "offset": 0,
  "has_more": false
}
```

最后消息查询应复用首页最近会话接口已有的关联子查询方式，查询次数不能随 Session 数量线性增长。

## 7. 后端实现约束

### 7.1 记忆替代判断

替代关系只在当前 Persona 继承链内生效：

```text
父故事：A
├─ 子故事 1：B supersedes A
└─ 子故事 2：仍可看到 A
```

不得在 `memory_chunks` 表增加全局 `is_superseded` 持久化字段。

分页前应构造当前链可见的替代目标子查询：

```python
visible_superseded_ids = (
    db.query(MemoryChunk.supersedes_id)
    .filter(
        MemoryChunk.persona_id.in_(ancestor_persona_ids),
        MemoryChunk.supersedes_id.isnot(None),
    )
)
```

然后将 `active/superseded` 条件应用到主查询，再执行 `offset/limit`。

### 7.2 数据源

- SQLite：记忆正文、来源、继承、替代、管理列表和统计的权威来源。
- ChromaDB：仅用于语义召回，不用于管理列表和统计。
- Outbox：继续负责 SQLite 与向量库之间的最终一致性同步。

### 7.3 Service 边界

当前实现位于 `app-backend/services/memory/session_memory_query_service.py`：

- `query_session_memories`：继承链查询、服务端筛选、分类统计及分页。
- `serialize_memory_item`：序列化记忆字段。
- `get_character_memory_overview`：复用会话列表，批量读取 Persona 和记忆，生成每条故事的统计。

分类统计由查询服务内部计算。Router 负责 Query 参数校验、调用服务和 HTTP 异常转换。

### 7.4 数据库索引

迁移 `app-backend/alembic/versions/b1c2d3e4f5a6_add_memory_navigation_indexes.py` 已创建：

```sql
CREATE INDEX ix_memory_chunks_persona_created_id
ON memory_chunks (persona_id, created_at DESC, id DESC);

CREATE INDEX ix_chat_messages_session_active_created_id
ON chat_messages (session_id, is_active, created_at DESC, id DESC);
```

索引随 Alembic 升级应用，不需要再按旧计划手动新增。

## 8. 前端接入标准

### 8.1 记忆列表

1. 切换分类时设置 `offset = 0` 并重新请求服务端。
2. 搜索词变化后防抖请求，搜索条件必须随分类一同发送。
3. 只有请求完成且 `total === 0` 时才显示分类空状态。
4. 是否继续加载只读取服务端 `has_more`。
5. 加载更多时追加 `items`，不得重新执行本地分类。
6. 新增、编辑和删除后重新加载当前分类第一页。
7. 应忽略晚于新请求返回的旧搜索响应，避免快速输入时列表倒退。

### 8.2 角色记忆导航

1. 首次进入角色详情的记忆标签时请求 `memory-overview`。
2. 最近活跃卡片使用 `recent_session_id`，不由前端猜测。
3. 点击故事后将 `session_id` 和 `title` 传入记忆管理组件。
4. 角色页记忆弹窗使用“此故事”；聊天页继续使用“当前故事”。
5. 角色导航不得把不同故事线的记忆合并成可直接编辑的扁平列表。

## 9. 兼容边界

`GET /sessions/{session_id}/memories` 当前始终返回分页对象，不再返回裸数组。前端按对象中的 `items`、`total`、`has_more` 和 `facets` 读取结果。

当前没有兼容旧裸数组响应的参数。部署时应使用同一版本的前后端。记忆列表仍使用 offset 分页，没有实现记忆 cursor 分页或角色级跨故事搜索接口。

## 10. 验收用例

| 编号 | 场景 | 预期 |
| --- | --- | --- |
| M-01 | 前 20 条均为本地记忆，第 21 条为继承记忆 | `scope=inherited` 第一页能返回该继承记忆 |
| M-02 | 子分支记忆 B 替代祖先记忆 A | 子分支 `status=active` 不返回 A |
| M-03 | 子分支 1 用 B 替代 A，查询兄弟分支 2 | 兄弟分支仍返回 A |
| M-04 | 查询 `scope=local&status=active` | `total` 与 `facets.local_active` 在无搜索时一致 |
| M-05 | 输入搜索词并切换分类 | `facets` 反映搜索结果中的各分类数量 |
| M-06 | 多条记忆拥有相同 `created_at` | 多次请求分页结果顺序一致且无重复 |
| M-07 | 删除当前页一条记忆 | 重新加载后 `total/facets/has_more` 正确 |
| M-08 | 角色拥有父、子、兄弟三条故事线 | 概览统计符合各自 Persona 继承链 |
| M-09 | 角色拥有大量 Session | 会话预览和记忆概览不存在逐 Session 的 N+1 查询 |
| M-10 | Character 不存在 | `memory-overview` 返回 `404` |
