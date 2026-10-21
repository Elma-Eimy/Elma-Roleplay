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
| `source_message_id` | integer | 是 | 来源消息范围终点 |
| `supersedes_id` | integer | 是 | 当前记忆直接替代的前一版本 |
| `is_superseded` | boolean | 否 | 在当前 Persona 继承链中是否已被替代 |

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
| `superseded` | 当前继承链可见、但已被链上新版本替代的旧记忆 |

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
| `superseded` | 当前继承链中已被新版本替代的旧记忆 |
| `all` | 有效与已替代记忆 |

### 前端分类映射

| UI 分类 | `scope` | `status` |
| --- | --- | --- |
| 全部 | `all` | `active` |
| 当前故事／此故事 | `local` | `active` |
| 继承 | `inherited` | `active` |
| 已替代 | `all` | `superseded` |

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
