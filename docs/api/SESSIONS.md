# 会话、消息与记忆 API

[API 总表](../../API_TABLE.md) · [接口维护与校验](README.md)

快速定位：[当前状态](#current-role-state) · [创建故事](#post-sessionscreate) · [历史消息](#get-sessionssession_idhistory) · [记忆列表](#get-sessionssession_idmemories) · [记忆整理](#memory-consolidation-sessionssession_idmemory-consolidations) · [Prompt 预览](#get-sessionssession_idcompile_prompt)

## Current role state

`GET /sessions/{session_id}/role-state` returns `{session_id, revision, state}`. `revision` is a 64-character SHA-256 digest of the branch baseline and active message/state sequence. `state` contains optional `scene` and `characters`, where character names map to optional `posture`, `clothing`, and `location` strings. Unknown fields may be absent; an explicitly cleared scene is `null` and does not restore the opening location.

`PUT /sessions/{session_id}/role-state` accepts:

<!-- request-example: PUT /sessions/{session_id}/role-state -->
```json
{
  "expected_revision": "0000000000000000000000000000000000000000000000000000000000000000",
  "patch": {
    "scene": "客厅",
    "characters": {"露娜": {"posture": "坐在沙发上", "clothing": "白色衬衫", "location": "窗边"}}
  }
}
```

- Returns the updated GET shape. Omitted fields remain unchanged; manual `null` or empty string clears a field. Clearing all known fields removes that character's state. Scene limit: 300 characters; character names: 1–50 characters; posture/clothing/location: 1–200 characters; at most 8 characters in the resulting state. Up to 16 character entries are allowed in a manual patch to clear old entries while adding new ones. Unknown keys, invalid types, oversized payloads or invalid revisions return `422`.
- Missing session/persona returns `404`. A stale revision or a session currently generating a reply returns `409`. Corrections attach to the latest active local message, or the baseline when no messages exist, and affect subsequent prompt assembly. Reads do not call an LLM.
- Chat generation must append an increment such as `<state_update>{"scene":"客厅","characters":{"露娜":{"posture":"站着"}}}</state_update>` after reply/status when state changes or is first explicitly described; the entire increment may be omitted when nothing changes. This is an internal model-output protocol, not an extra SSE event. Only changed or first explicitly described fields are emitted; omitted updates preserve state. LLM patches cannot clear fields or use nulls. Invalid patches are ignored atomically while reply/status are retained; raw state tags never enter stored reply text or streamed body chunks.
- Active candidates determine state. Regeneration starts before the replaced candidate; branches snapshot only their selected message boundary. Editing assistant text invalidates that message's model-derived patch, preserving manual corrections. Existing emotion/affection behavior remains separate. See [role-state behavior](../../docs/features/ROLE_STATE.md) for scope and limitations.


立绘管理和会话选图见 [角色与立绘接口](CHARACTERS.md#manual-character-portraits)。

## POST `/sessions/create`

`parent_session_id` 为整数时从父故事分叉，省略或 `null` 时新建故事；可选的 `greeting_index` 选择开场，`start_message_id` 指定分叉消息节点。

* **Request (JSON)**:
<!-- request-example: POST /sessions/create -->
  ```json
  {
    "character_id": 1,
    "parent_session_id": null,
    "title": "测试对话 1",
    "greeting_index": null,
    "start_message_id": null
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "message": "Session created successfully",
    "session_id": 1,
    "persona_id": 1,
    "character_id": 1,
    "inherited": false,
    "title": "测试对话 1"
  }
  ```

## GET `/sessions`
* **Query Parameters**:
  - `character_id`: Filter sessions by Character ID (Required)
  - `include_last_message`: Include the last active message (default `true`).
  - `limit`: Page size, `1~100` (default `50`).
  - `offset`: Pagination offset, at least `0` (default `0`).
* **Response (200 OK)**:
  ```json
  {
    "character_id": 1,
    "sessions": [
      {
        "id": 1,
        "title": "测试对话 1",
        "parent_session_id": null,
        "fork_message_id": null,
        "created_at": "2026-05-23T16:00:19",
        "updated_at": "2026-05-23T16:05:00",
        "persona": {
          "id": 1,
          "affection_score": 10,
          "current_mood": "平静"
        },
        "last_message": {
          "content": "你好呀！",
          "created_at": "2026-05-23T16:05:00"
        }
      }
    ],
    "total": 1,
    "limit": 50,
    "offset": 0,
    "has_more": false
  }
  ```

## GET `/sessions/recent`
* **Purpose**: Home-screen aggregate endpoint. The backend should fetch sessions, character summaries, and each session's latest active message in one database query (or a bounded query set) to avoid client-side N+1 requests.
* **Query Parameters**:
  - `limit`: Page size, `1~100` (backend default: `50`).
  - `offset`: Pagination offset, at least `0` (default: `0`).
* **Response (200 OK)**:
  ```json
  {
    "sessions": [
      {
        "id": 1,
        "title": "测试对话 1",
        "parent_session_id": null,
        "created_at": "2026-05-23T16:00:19",
        "updated_at": "2026-05-23T16:05:00",
        "persona": {
          "id": 1,
          "affection_score": 10,
          "current_mood": "平静"
        },
        "character": {
          "id": 1,
          "name": "测试小助手",
          "avatar_path": "assets/avatars/4a6b2c8d_helper.png"
        },
        "last_message": {
          "content": "你好呀！有什么我可以帮你的吗？",
          "created_at": "2026-05-23T16:05:00"
        }
      }
    ],
    "total": 1,
    "limit": 50,
    "offset": 0,
    "has_more": false
  }
  ```

## GET `/sessions/{session_id}`
* **Response (200 OK)**:
  ```json
  {
    "id": 1,
    "title": "测试对话 1",
    "parent_session_id": null,
    "created_at": "2026-05-23T16:00:19",
    "updated_at": "2026-05-23T16:05:00",
    "persona": {
      "id": 1,
      "character_id": 1,
      "affection_score": 10,
      "cognition_state": "角色自我认知状态...",
      "current_mood": "平静",
      "current_scenario_override": "学校"
    },
    "character": {
      "id": 1,
      "name": "测试小助手",
      "avatar_path": "assets/avatars/4a6b2c8d_helper.png"
    }
  }
  ```

## GET `/sessions/{session_id}/history`
* **Query Parameters**:
  - `limit`: Maximum number of messages to retrieve (Defaults to backend `APP_HISTORY_FETCH_DEFAULT`)
  - `before_id`: Optional. Fetch messages before this specific message ID for cursor-based pagination
* **Response (200 OK)**:
  ```json
  {
    "session_id": 1,
    "messages": [
      {
        "id": 1,
        "role": "assistant",
        "content": "你好呀！有什么我可以帮你的吗？",
        "reasoning_content": null,
        "emotion_tag": "平静",
        "affection_change": 0,
        "created_at": "2026-05-23T16:00:19",
        "parent_id": null,
        "is_active": true,
        "audio_path": null,
        "candidates": [
          {
            "id": 1,
            "content": "你好呀！...",
            "reasoning_content": null,
            "emotion_tag": "平静",
            "affection_change": 0,
            "created_at": "2026-05-23T16:00:19",
            "audio_path": null
          }
        ],
        "active_index": 0
      }
    ],
    "is_generating": false
  }
  ```
  *(Note: `is_generating` is `true` if this session is generating when the history read begins or ends. Generation finishing during the read may conservatively return `true`; fetch history again until it becomes `false` to obtain the final messages.)*

## PUT `/sessions/{session_id}/title`
* **Request (JSON)**:
<!-- request-example: PUT /sessions/{session_id}/title -->
  ```json
  {
    "title": "新剧情线"
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "message": "Session title updated successfully",
    "session_id": 1,
    "title": "新剧情线"
  }
  ```

## DELETE `/sessions/{session_id}` (or POST `/sessions/{session_id}/delete`)
* **Response (200 OK)**:
  ```json
  {
    "message": "Session deleted successfully",
    "deleted_session_id": 1,
    "relinked_children": 1,
    "memories_deleted": 2
  }
  ```

## POST `/sessions/{session_id}/trigger_summary`
手动提纯只可靠入队，立即返回当前处理状态，不在 HTTP 请求内调用模型。Worker 会提取新消息并收尾本故事的有效进行中事件；没有新消息时也可处理已保存缓冲。缓冲本身不计入记忆列表或统计。

`extracted_count` 保留兼容，但该异步入口本次固定返回 `0`；实际新增结果通过记忆列表与日志查看。候选可靠保存后推进接收指针，关系判断失败不必重新提取。`status` 为 `completed/pending/retrying/failed`，`pending_count` 表示尚未完成的任务数，`error_codes` 仅返回脱敏原因码；`failed` 表示最近任务因来源失效被取消。新请求通常返回 `pending`，前端不能把受理提示显示成整理完成。失败候选由独立 Worker 退避重试，无需继续聊天。

* **Response (200 OK)**:
  ```json
  {
    "message": "记忆已接收，后台处理中",
    "session_id": 1,
    "extracted_count": 0,
    "status": "pending",
    "pending_count": 1,
    "error_codes": []
  }
  ```

## POST `/sessions/{session_id}/trigger_cognition`
* **Response (200 OK)**:
  ```json
  {
    "message": "认知更新已完成",
    "session_id": 1,
    "cognition_state": "角色当前的新认知文本..."
  }
  ```

## PUT `/sessions/messages/{message_id}`
* **Request (JSON)**:
<!-- request-example: PUT /sessions/messages/{message_id} -->
  ```json
  {
    "content": "修改后的消息文本"
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "message": "Message updated successfully",
    "message_id": 1,
    "content": "修改后的消息文本"
  }
  ```

## DELETE `/sessions/messages/{message_id}` (or POST `/sessions/messages/{message_id}/delete`)
* **Response (200 OK)**:
  ```json
  {
    "message": "Message deleted successfully",
    "message_id": 1
  }
  ```

## GET `/sessions/{session_id}/memories`
* **Query Parameters**:
  - `q`: Optional content keyword, at most 200 characters.
  - `scope`: `all`, `local`, or `inherited` (default `all`).
  - `status`: `active`, `superseded`, or `all` (default `active`).
  - `limit`: Page size, `1~100` (default `20`).
  - `offset`: Pagination offset, at least `0` (default `0`).
* **Memory provenance and versioning fields**:

  | Field | Type | Description |
  | :--- | :--- | :--- |
  | `source_start_message_id` | `integer \| null` | First message in the smallest continuous source range supporting this memory. `null` for legacy or manually created memories without a chat source. |
  | `source_message_id` | `integer \| null` | Last message in the source range supporting this memory. The name is retained for database compatibility. |
  | `supersedes_id` | `integer \| null` | ID of the older memory directly superseded by this memory, or `null` when there is no explicit replacement relationship. |
  | `is_superseded` | `boolean` | Whether this original card is hidden by a visible replacement or applied consolidation in the current story. |
  | `consolidation_id` | `integer \| null` | Consolidation record producing this card; ordinary originals use `null`. |

* **Response (200 OK)**:
  ```json
  {
    "items": [
      {
        "id": 1,
        "content": "昨天用户跟我聊到了 Python Web 开发，我们都觉得 FastAPI 是非常棒的框架。",
        "memory_type": "fact",
        "importance_score": 0.85,
        "is_local": true,
        "created_at": "2026-05-23T16:00:19",
        "origin_session_id": 1,
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
  Inheritance scope, keyword search, replacement status, and `total` are all applied
  before pagination. Results use stable ordering by `created_at DESC, id DESC`.
  `facets` applies `q`, but is calculated before the current `scope` and `status`
  filters, so category counts update with search while remaining comparable.

  `effective_total` is `local_active + inherited_active`. `has_more` is true exactly
  when `offset + items.length < total`. Invalid query values return `422`; a missing
  Session or Persona returns `404`.

  `is_superseded` is calculated relative to the session in the request. A replacement
  created on one child branch does not globally invalidate the same old memory on its
  parent or sibling branches. Superseded records remain stored, but are excluded by
  the default `status=active`. Use `status=superseded` or `status=all` to retrieve them.

## POST `/sessions/{session_id}/memories`

`importance_score` 可选，默认 `0.8`；`memory_type` 可选，默认 `fact`，可选值为 `event`、`emotion`、`relationship`、`fact`。

* **Request (JSON)**:
<!-- request-example: POST /sessions/{session_id}/memories -->
  ```json
  {
    "content": "这是一家开在转角处的日式猫咪咖啡厅，环境清静舒适。",
    "importance_score": 0.9,
    "memory_type": "fact"
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "message": "Memory added successfully",
    "memory": {
      "id": 5,
      "content": "这是一家开在转角处的日式猫咪咖啡厅，环境清静舒适。",
      "memory_type": "fact",
      "importance_score": 0.9,
      "is_local": true,
      "created_at": "2026-05-23T16:10:00",
      "origin_session_id": 1,
      "source_start_message_id": null,
      "source_message_id": null,
      "supersedes_id": null,
      "is_superseded": false
    }
  }
  ```
  Manually created memories have no chat source or automatic replacement relationship,
  so `source_start_message_id`, `source_message_id`, and `supersedes_id` are `null`,
  and `is_superseded` is `false`.

## PUT `/sessions/{session_id}/memories/{memory_id}`
* **Request (JSON)**:
<!-- request-example: PUT /sessions/{session_id}/memories/{memory_id} -->
  ```json
  {
    "content": "修改后的记忆文本内容",
    "importance_score": 0.8
  }
  ```
  Manual editing corrects the existing memory in place. It does not create a new
  replacement version or change the source/version relationship fields.
* **Response (200 OK)**:
  ```json
  {
    "message": "Memory updated successfully",
    "memory": {
      "id": 5,
      "content": "修改后的记忆文本内容",
      "importance_score": 0.8,
      "source_start_message_id": null,
      "source_message_id": null,
      "supersedes_id": null
    }
  }
  ```

## DELETE `/sessions/{session_id}/memories/{memory_id}`
* **Response (200 OK)**:
  ```json
  {
    "message": "Memory deleted successfully",
    "memory_id": 5
  }
  ```

## Memory consolidation (`/sessions/{session_id}/memory-consolidations`)

请求示例中的版本号和分组编号只说明格式，提交前应使用当前预览返回的实际值。

<!-- request-example: POST /sessions/{session_id}/memory-consolidations/preview -->
```json
{"after_id": 0, "mode": "incremental"}
```

<!-- request-example: POST /sessions/{session_id}/memory-consolidations/{batch_id}/apply -->
```json
{"group_ids": [0], "expected_revision": 0}
```

<!-- request-example: PUT /sessions/{session_id}/memory-consolidations/{batch_id}/groups/{group_id} -->
```json
{"expected_revision": 0, "content": "保留原有事实与来源的审阅内容", "ignored": false, "ignore_reason": ""}
```

| Method | Path suffix | Request | Response |
| --- | --- | --- | --- |
| GET | (none) | `limit=10` (1–20), `offset=0` (≥0) | `{ "items": [Consolidation], "total": 12, "limit": 10, "offset": 0, "has_more": true, "scan_status": ScanStatus }`, local records in descending ID order |
| POST | `/preview` | `{ "after_id": 0, "mode": "full" }`; mode is `full` (default) or `incremental`; incremental requires after_id=0 | `Consolidation` |
| POST | `/{batch_id}/apply` | `{ "group_ids": [0], "expected_revision": 0 }`, 1–12 distinct non-negative indices | `Consolidation` |
| PUT | `/{batch_id}/groups/{group_id}` | `{ "expected_revision": 0, "content": "Reviewed content", "ignored": false, "ignore_reason": "" }` | `Consolidation` |
| POST | `/{batch_id}/undo` | None | `Consolidation` |

`Consolidation` contains `id`, `status` (`preview/applied/undone`), `created_at`, `sources` (original-card snapshots), `groups` (`id`, `kind: duplicate/event`, `source_ids`, `content`, `reason`), `selected_group_ids`, `results` (`id`, `content`), `scanned_count`, `remaining_count`, `has_more`, and `next_after_id`.

Source snapshots may additionally carry `temporal_status` (`unknown/current/historical/planned`) and `temporal_note` (string or null); legacy records may omit them. Preview and apply reject groups mixing story-time statuses or notes; summaries preserve matching values. Chat semantic and graph recall share SQLite fact IDs, story/fork cutoffs, deduplication and a joint budget; consolidated originals map to active summaries. New automatic-card message fingerprints are revalidated before injection; legacy/manual cards without snapshots retain compatibility. Ordinary memory-list fields and counts are unchanged.

Source snapshots may also carry an integer `event_id`. Different explicit event identities cannot be consolidated; summaries of stages sharing the same identity preserve it. Automatic ongoing events keep their identity across capacity or three-batch checkpoints; manual extraction saves a stage without closing the identity. Stage cards count as ordinary long-term memories, while pending fragments do not. Identity association alone never widens story/fork visibility.

Automatic admission distinguishes persistent states, episodes and transient reactions through internal model metadata; `retention/event_index` are not new HTTP or memory-list fields. Reactions with a verified same-batch event association retain their text and provenance inside that event. State refinements preserve old conditions and verified message evidence; unsupported legacy/ancestor refinements remain separate. Candidate lookup supplements recent cards with bounded older nearest neighbors even outside the distance threshold, without changing branch visibility or treating distance as permission to merge.

Manual scan modes: `full` scans eligible originals after the ID cursor regardless of earlier checks; `incremental` scans only originals whose current fingerprint has not been checked, including changed low-ID cards, and continues with after_id=0. Neither mode clusters across batches or adds previously checked cards to incremental input. Successful model responses (including empty suggestions) atomically save the preview and unchanged source fingerprints. Failures do not advance progress; edits/deletions during model generation are not recorded as checked. With fewer than two sources, no model is called and no card is marked checked. Apply/undo does not reset checked versions. Existing previews remain intact on upgrade; their old scan progress is not inferred.

If any source of a suggested group changes or becomes ineligible during generation, this scan also defers the remaining sources of that group so a later incremental scan can retry together. Other valid groups advance normally; records from newer successful scans are preserved.

New record fields: `scan_mode` (legacy default `full`), `model_checked` (whether at least two cards were sent and the response validated), `recorded_count` (unchanged source versions recorded this time). `remaining_count` is the number of cards in the requested scope before this batch. Full-mode `has_more` follows the ID cursor; incremental `has_more` means at least two pending cards remain at save time. One pending card waits for another or for a later manual full scan. `ScanStatus` contains current `eligible_count`, `checked_count`, `pending_count`; list GET returns it once at the top level, while individual POST/PUT responses include `scan_status`. Counts cover only active local ordinary cards, excluding inherited/hidden originals and summaries. Checked does not mean reviewed or applied; saved suggestions remain available through history. Progress uses SQLite `memory_consolidation_scans`, not ChromaDB; the internal fingerprint is not exposed over HTTP.

Review adds batch `review_revision` (legacy records default to 0) and group `original_content`, `ignored`, `ignore_reason`, `conflict` (message or null). PUT is allowed only for previews: optional trimmed content is 4–500 characters, reason is at most 160 characters, ignored defaults to false. Omit content to change only review metadata, including on stale groups. Each save increments the revision; stale revisions return 409. Apply defaults its expected revision to 0 for older clients, uses saved reviewed content, and rejects ignored or conflicting selected groups. Unselected conflicts do not block valid groups. Ignore is limited to this preview and can be reversed before apply; it does not suppress future previews. Review preserves model originals and source snapshots in the existing JSON record, without memory/vector writes or a schema migration. Generation locks also block review saves.

Each preview scans at most 100 active local original cards in ID order. Inherited cards and consolidation outputs are excluded. Preview persists suggestions without changing memories; apply accepts only saved group indices, atomically revalidates unchanged sources, preserves originals, creates derived cards/source links/story scope, and queues vector Outbox tasks. Repeating the same apply/undo is idempotent. Selected originals enter the existing `superseded` category (UI: 历史原卡); active counts and retrieval use the same story view. Filters still run before pagination.

Preview omits an entire suggested group when its event sources contain conflicting explicit occurrence dates; safe groups remain selectable and omitted sources remain active. Apply rechecks the same boundary, including previously saved previews, returning `409` on conflict. Appointment/plan target dates are not treated as occurrence dates. This conservative guard recognizes numeric Chinese calendar dates, `YYYY-MM-DD`/`YYYY/MM/DD`, and explicit years; it does not resolve relative dates or guarantee semantic event identity.

For `duplicate` suggestions, sources with differing explicit negation markers are also omitted and rechecked on apply. This favors keeping originals over combining positive/negative facts; absence of a recognized marker does not prove semantic equivalence, and differently phrased equivalent facts may conservatively remain separate.

Forks copy enabled consolidation scopes with at least one group visible at creation and respect source-message cutoffs; later parent apply/undo does not change existing children. Sources referenced by actually visible consolidation groups and derived outputs are read-only (`409` for ordinary edit/delete); invisible legacy scope associations do not lock originals. Undo restores originals only in the current story and retains referenced outputs for existing forks. Subsequent replacements visible in the current story block undo with `409`; child-only replacements do not prevent parent undo. Graph/cognition/message state is unchanged.

Source-message foreign-key references may become `null` after deletion. An internal persistent source upper bound still enforces branch isolation for original cards and derived summaries; HTTP response fields are unchanged. Upgrade restores known cutoffs from existing references and saved consolidation snapshots where available. Truly manual cards without message provenance retain their inheritance behavior.

Errors: `404` for missing story/local record; `422` for invalid request; `409` for changed sources, conflicting state or apply/undo during generation; `502` for failed/invalid model suggestions. Model input is partitioned by memory type, with IDs restricted to each call; non-event cards only support duplicate removal. Sequential type calls share the 12-group preview budget, reserve one slot for each later type with at least two cards, and persist together atomically. Preview accepts a bare model group array after normalization and retries JSON/outer-structure/group-count/source-memory-type errors at most once per type with the same sources; all source and content checks remain required. Truncated output is reported separately. `[MEMORY CONSOLIDATION]` backend logs contain structural diagnostics without card/model text. Full payload/lifecycle rules: [Memory API](../../docs/api/MEMORY_API.md#可预览的存量记忆整理). New vectors synchronize asynchronously; recall may temporarily omit results until Outbox upsert completes.

## GET `/sessions/{session_id}/compile_prompt`
* **Query Parameters**:
  - `user_nickname`: Nickname of the user (defaults to "用户")
* **Response (200 OK)**:
  ```json
  {
    "messages": [
      {
        "role": "system",
        "content": "... (Compiled System Prompt containing人设, RAG recalls, Lorebook additions and Cognition status) ..."
      },
      {
        "role": "user",
        "content": "... (Compiled user message with context wrappers) ..."
      }
    ],
    "token_estimate": {
      "characters": 18420,
      "estimated_tokens": 12800,
      "lower_bound": 9760,
      "upper_bound": 16720,
      "method": "heuristic_v1",
      "is_exact": false,
      "sections": {
        "character": {
          "characters": 8200,
          "estimated_tokens": 6100,
          "lower_bound": 4800,
          "upper_bound": 7600
        },
        "recent_history": {"characters": 6000, "estimated_tokens": 3900, "lower_bound": 3000, "upper_bound": 5000},
        "scenario": {"characters": 300, "estimated_tokens": 220, "lower_bound": 150, "upper_bound": 350},
        "cognition": {"characters": 500, "estimated_tokens": 350, "lower_bound": 250, "upper_bound": 500},
        "status": {"characters": 120, "estimated_tokens": 90, "lower_bound": 60, "upper_bound": 150},
        "lorebook": {"characters": 900, "estimated_tokens": 600, "lower_bound": 400, "upper_bound": 850},
        "long_term_memory": {"characters": 1000, "estimated_tokens": 700, "lower_bound": 500, "upper_bound": 1000},
        "graph": {"characters": 400, "estimated_tokens": 280, "lower_bound": 190, "upper_bound": 420},
        "current_user_message": {"characters": 800, "estimated_tokens": 520, "lower_bound": 380, "upper_bound": 750},
        "other": {"characters": 200, "estimated_tokens": 40, "lower_bound": 30, "upper_bound": 100}
      }
    }
  }
  ```
* **Token estimate sections**:

  | Section | Content |
  | :--- | :--- |
  | `character` | Character definition, output requirements, examples, supplemental rules, and other prompt instructions. |
  | `recent_history` | Recent and inherited history injected before the current user message. |
  | `scenario` | Current scenario. |
  | `cognition` | Persona cognition state. |
  | `status` | Current mood and affection status. |
  | `lorebook` | Lorebook content activated for this turn. |
  | `long_term_memory` | Long-term memory cards recalled for this turn. |
  | `graph` | Knowledge-graph relationships recalled for this turn. |
  | `current_user_message` | The latest user message and its fixed heading. |
  | `other` | Dynamic context framing, section separators, and estimated chat-protocol overhead. |

  `sections` always contains every section above, including zero-valued sections.
  `estimated_tokens` is a display-oriented midpoint, while `lower_bound` and
  `upper_bound` intentionally provide a wider likely range. `characters` counts only
  visible message content; estimated protocol overhead in `other` has no corresponding
  character count.

  This is an observational heuristic (`method: "heuristic_v1"`): it never truncates or
  rewrites the compiled prompt. It does not use a model-provider tokenizer and is not
  suitable for billing calculations, so `is_exact` is always `false`. The actual token
  count varies with the target model, language mix, special characters, and provider
  message templates.

  Long-term-memory retrieval used to assemble the prompt excludes memories superseded
  on the current Persona ancestry chain. The old records remain available through the
  memories list endpoint.

---
