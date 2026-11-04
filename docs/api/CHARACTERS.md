# 角色、导入与立绘 API

[API 总表](../../API_TABLE.md) · [接口维护与校验](README.md)

快速定位：[角色导入](#post-charactersparse) · [阅读翻译](#post-characterstranslate) · [角色管理](#post-characterscreate) · [立绘与选图](#manual-character-portraits) · [CHARX](#conservative-charx-import)

## POST `/characters/parse`
* **Request**: `multipart/form-data`
  - `file`: PNG Character Card containing SillyTavern metadata (tEXt/zTXt/iTXt) or standard JSON config file.
* **Storage**: Parsing does not create a database record. Valid PNGs are retained as content-addressed avatars; identical uploads reuse the same path. Clients should use the returned `avatar_path` without uploading the image again. JSON uploads and failed parses are temporary and leave no avatar file. With multiple valid `chara` chunks, the first is used. See [character card compatibility](../../docs/features/CHARACTER_CARDS.md).
* **Metadata**: `data.extensions.ai_roleplay_card` preserves `creator`, `character_version`, `spec` and `spec_version` when supplied by the card. `extensions.alternate_greetings` and `extensions.character_book` remain the persisted opening and embedded-lorebook fields. Clients preview the parsed data before applying it.
* **Response (200 OK)**:
  ```json
  {
    "message": "Character parsed successfully",
    "data": {
      "name": "测试小助手",
      "description": "你是一个热心、活泼的AI小助手...",
      "personality": "开朗、热情",
      "scenario": "咖啡厅",
      "first_mes": "你好呀！",
      "mes_example": "示例对话...",
      "creator_notes": "",
      "system_prompt_override": "",
      "post_history_instructions": "",
      "tags": ["helper"],
      "extensions": {},
      "avatar_path": "assets/avatars/4a6b2c8d_helper.png"
    }
  }
  ```

## POST `/characters/translation-cache`

<!-- request-example: POST /characters/translation-cache; POST /characters/translate -->
```json
{"card": {"name": "Traveler", "description": "English background", "first_mes": "Hello {{user}}", "extensions": {"alternate_greetings": ["", "Another greeting"]}}, "force": false}
```
* **Request (JSON)**: `{ "card": { "name": "Traveler", "description": "English background", "first_mes": "Hello {{user}}", "extensions": { "alternate_greetings": ["", "Another greeting"] } } }`.
* `card` accepts the same source fields as character creation; only `description`, `personality`, `scenario`, `first_mes`, `mes_example`, `creator_notes`, and `extensions.alternate_greetings` form the cache key. Unknown/non-string alternate items normalize to empty strings without shifting indexes.
* **Response (200)**: `{ "translation": null }` on a miss; on a hit returns the same translation object as `/characters/translate`. This endpoint never invokes a model or creates a character. Reading content above 120,000 characters returns `400`.

## POST `/characters/translate`
* **Request (JSON)**: Same `card` object as cache lookup, with optional `force: true` to regenerate an existing copy (default `false`). No saved character ID is required.
* **Response (200)**:
  ```json
  {
    "translation": {
      "source_hash": "sha256-of-versioned-reading-source",
      "model": "deepseek-flash",
      "created_at": "2026-10-20T12:00:00",
      "fields": {
        "description": "中文背景",
        "personality": "",
        "scenario": "",
        "first_mes": "你好 {{user}}",
        "mes_example": "",
        "creator_notes": "",
        "alternate_greetings": ["", "另一个开场"]
      }
    }
  }
  ```
* Uses `translation_model` and the existing chat provider connection. Long cards are segmented using a coarse length mapping (ASCII characters count as 0.25, others as 1), with up to 2,400 mapped units per segment. Each batch has at most three segments and 9,600 raw text characters in total; the output token ceiling is raised from 8,192 to 32,768. The 120,000 raw character input limit is unchanged. The complete result is committed to SQLite atomically. Invalid/truncated model output, changed placeholders or translation service failures return `502`; the original card and previous successful cache are retained. Invalid request shapes return `422`.
* Translations are reading-only: no character, worldbook, prompt, greeting index or chat message is updated. Name, tags and hidden prompt fields remain in the original language. Cache entries survive character deletion and may be reused after reimporting the same content.

## POST `/characters/create`
* **Duplicate handling**: The response includes `created: true` for a new record, or `created: false` with the existing `character_id` and `name` for an existing exact name. The latter does not apply the submitted settings. Clients must prompt the user instead of silently opening a story with the old card.
* **Request (JSON)**:
<!-- request-example: POST /characters/create; PUT /characters/{character_id} -->
  ```json
  {
    "name": "测试小助手",
    "avatar_path": "assets/avatars/4a6b2c8d_helper.png",
    "description": "人设描述...",
    "personality": "性格...",
    "scenario": "咖啡厅",
    "first_mes": "开场白...",
    "mes_example": "对话示例...",
    "creator_notes": "作者寄语",
    "system_prompt_override": "覆盖系统提示",
    "post_history_instructions": "历史末端指令",
    "tags": ["helper", "funny"],
    "extensions": {}
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "message": "Character created successfully",
    "character_id": 1,
    "name": "测试小助手"
  }
  ```

## GET `/characters`
* **Query Parameters**:
  - `limit`: Optional page size limit.
  - `offset`: Optional page offset.
* **Response (200 OK)**:
  ```json
  {
    "characters": [
      {
        "id": 1,
        "name": "测试小助手",
        "avatar_path": "assets/avatars/4a6b2c8d_helper.png",
        "description": "描述摘要..."
      }
    ]
  }
  ```

## GET `/characters/{character_id}`
* **Response (200 OK)**:
  ```json
  {
    "id": 1,
    "name": "测试小助手",
    "avatar_path": "assets/avatars/4a6b2c8d_helper.png",
    "description": "详细人设设定...",
    "personality": "性格...",
    "scenario": "咖啡厅",
    "first_mes": "开场白...",
    "mes_example": "对话示例...",
    "creator_notes": "作者留言",
    "system_prompt_override": "系统设定覆盖",
    "post_history_instructions": "历史末端注入指令",
    "tags": ["helper"],
    "extensions": {},
    "lorebooks": [
      {
        "id": 1,
        "name": "新手教学世界书"
      }
    ],
    "created_at": "2026-05-23T16:00:19"
  }
  ```

## GET `/characters/{character_id}/memory-overview`
* **Query Parameters**:
  - `limit`: Page size, `1~100` (default `50`).
  - `offset`: Pagination offset, at least `0` (default `0`).
* **Response (200 OK)**:
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
  Sessions are ordered by `updated_at DESC, id DESC`. `recent_session_id` is the
  first session in that complete ordering, even when the requested page has a nonzero
  offset. `last_message` includes only active messages. A missing character returns
  `404`; invalid pagination returns `422`.

## PUT `/characters/{character_id}`
* **Request (JSON)**: Same format as `POST /characters/create`.
* **Response (200 OK)**:
  ```json
  {
    "message": "Character updated successfully",
    "character_id": 1,
    "name": "测试小助手"
  }
  ```

## DELETE `/characters/{character_id}` (or POST `/characters/{character_id}/delete`)
* **Response (200 OK)**:
  ```json
  {
    "message": "Character and all associated sessions/memories deleted successfully",
    "character_id": 1,
    "sessions_deleted_count": 2,
    "collection_deleted": true
  }
  ```

---

## Manual character portraits

<!-- request-example: PUT /characters/{character_id}/portraits/{portrait_id} -->
```json
{"name": "便服"}
```

<!-- request-example: PUT /sessions/{session_id}/portrait -->
```json
{"portrait_id": 1, "expected_revision": "0000000000000000000000000000000000000000000000000000000000000000"}
```

上面的版本号为格式示例，实际更新需使用 GET 返回的当前版本。

`GET /characters/{character_id}/portraits` is paginated: optional `offset` (default 0) and `limit` (default 24, maximum 100), with additional `total` and `has_more` response fields. Imported portraits may also contain `source_type`, `source_name` and `source_uri`; manual portraits omit empty provenance fields.

* `GET /characters/{character_id}/portraits` returns `{ "portraits": [{ "id": 1, "name": "便服", "image_path": "assets/avatars/portrait_....png" }] }`, ordered by ID. A plain character returns an empty list.
* `POST /characters/{character_id}/portraits` accepts multipart `file`, verifies PNG/JPEG/WebP content and pixel decoding, the configured `SECURITY_MAX_CARD_SIZE_MB` limit and at most 25 million pixels. Returns the saved portrait object; invalid or truncated images return `422`, oversized uploads `413`, missing characters `404`. This upload attaches the resource immediately; failure before database commit removes the newly written file.
* `PUT /characters/{character_id}/portraits/{portrait_id}` accepts `{ "name": "便服" }` (trimmed, 1–80 characters, no control characters). Returns the portrait object. Names carry no automatic emotion or story meaning.
* `POST /characters/{character_id}/portraits/{portrait_id}/delete` returns `{ "message": "..." }`. Resources are shared by all stories of that character. Referencing stories fall back to the character avatar; cleanup uses Outbox and checks both avatar and portrait references. Missing or foreign portraits return `404`.
* `GET /sessions/{session_id}/portrait` returns `{ "session_id": 1, "portrait_id": null, "image_path": "avatar.png", "revision": "<64 hex characters>" }`. `null` means avatar fallback, including removed resources.
* `PUT /sessions/{session_id}/portrait` accepts `{ "portrait_id": 1, "expected_revision": "<revision from GET>" }`; explicit `null` restores avatar fallback. Returns the same shape as GET. A stale revision or active generation returns `409`; missing/foreign resources or invalid payloads return `422`; missing stories return `404`.
* Selections apply after the current latest active message (or the empty story baseline), persist across devices, and replay only active local messages. Regeneration and candidate switching restore that candidate's selection; forks snapshot the selected message boundary, including a nonactive candidate, without reading later parent changes. An empty parent story passes its portrait baseline to the new branch as an independent snapshot. Deleting a selection's message removes that override. The image ID is never reused after deletion.
* This version has no required tags, emotion classification, outfit groups or greeting bindings. Pure/character background mode remains a separate client preference; selecting an image does not turn on character background mode.

## Conservative CHARX import

<!-- request-example: POST /characters/charx/previews/{token}/import -->
```json
{"operation": "create_character", "portrait_indices": [0], "avatar_index": 0, "skip_duplicates": true}
```

素材编号需从当前预览中选择，示例不会保证某个编号在具体包中存在。

* `POST /characters/charx/preview` accepts exactly one multipart `file` with a `.charx` or `.zip` name and a root CCv3 3.0 `card.json`. This is separate from PNG/JSON `/parse`. Default file limit: 20 MiB, configured by `app.max_charx_size_mb` (restart required, effective range 1–100 MiB). ASGI middleware validates `X-API-Key` before reading any body, checks Content-Length and counts streamed bytes before multipart parsing. Total request limit is the file limit plus 64 KiB multipart overhead; absent Content-Length does not bypass it. Oversized requests/files return `413`, extra multipart files/fields `400`, upload idle for 30 seconds or total duration over 300 seconds `408`, invalid packages `422`, more than three active uploads `429`, and more than three pending previews `409`.
* Fixed limits: 60 MiB ZIP expansion, 1000 entries, 2 MiB card JSON, 8 MiB per image, 300 accepted image references, 25 million pixels per image, 250 million attempted decoded pixels and 60 MiB attempted image bytes per preview. Byte budget is reserved before reading and never refunded for invalid images. Each referenced ZIP entry is read/validated once, including failed entries; duplicate references reuse its result and staged files. Only stored/deflated, unencrypted archives with safe, unique, case-insensitive paths are accepted. Symlinks and nested archives are rejected. No archive member is extracted under its original path.
* Preview returns `{token,status:"ready",plan_version:1,package_sha256,expires_at,card,assets,compatibility,warnings,skipped_count,skipped_assets}`. `expires_at` is Unix seconds. Assets contain `{index,name,type,uri,ext,sha256,storage_index,referenced,animated?}`; `index` is the original manifest index, `storage_index` is internal staging metadata, `referenced` marks whether card text/openings/lorebook reference the asset, and `animated` marks original GIF/APNG/WebP animations preserved byte-for-byte; thumbnails are static, each animation is limited to 300 frames and all decoded frames count toward the pixel budget. Both `embeded://` and `embedded://` package URIs are accepted. `compatibility` contains `{status:"preserved"|"skipped"|"unknown",label,count}`; `skipped_assets` contains `{name,reason}`. Unknown extensions are explicitly unverified; an imported worldbook preserves entry data, not a guarantee of identical source-platform trigger behavior. Compatibility details are capped at 100 rows plus an omitted-count row.
* `GET /characters/charx/previews/{token}/images?offset=0&limit=12` returns `{images:[{index,thumbnail}],has_more}` with PNG data URLs. The maximum page size is 12. All endpoints use ordinary header authentication; temporary assets have no public URLs.
* `POST /characters/charx/previews/{token}/cancel` idempotently removes staged assets. Previews expire after 15 minutes. A lifespan-owned cleanup task runs at startup and every 60 seconds; request-driven cleanup remains available. Cancelled/expired status markers retain no card/image data and last another 15 minutes. Shutdown stops the task; cleanup resumes at the next startup. Staging is isolated by database path and follows the single-process deployment model. Expensive archive/image processing runs outside the lifecycle lock. Older preview-plan formats expire on access after upgrade.
* `POST /characters/charx/previews/{token}/import` accepts `{operation:"create_character"|"append_assets"|"update_character",skip_duplicates:true,character_id:null,name:null,portrait_indices:[],avatar_index:null,greeting_index?:number|null,card_mode?:"keep"|"replace"|"fill",sync_lorebook?:bool}`. For backward compatibility, omitted operation is inferred from `character_id` and whether card/lorebook/greeting updates are requested. Creating requires a null target; appending/updating requires an existing target and no name override. Pure `append_assets` requires at least one selected portrait or avatar and never changes character settings; `update_character` allows replacing (`card_mode:"replace"`) or filling empty fields (`card_mode:"fill"`), independently syncing the embedded worldbook (`sync_lorebook:true`; omitted, null or false preserves the existing worldbook), or promoting an alternate opening (`greeting_index`) to `first_mes`. `portrait_indices` contains at most 300 unique nonnegative indices. Null avatar preserves the existing avatar or creates without one.
* `skip_duplicates` defaults to true: portraits with matching SHA-256 in the target library or this selection are skipped, independent of source name and upload token. False permits duplicate portrait records; identical bytes within the target reuse a managed file. Missing managed files are not reused. Legacy portrait hashes are filled on demand; new uploads persist them. Avatar selection still applies even if the corresponding portrait is skipped.
* Confirmation returns `{character_id,created,portraits_added,duplicates_skipped,operation,package_sha256,card_updated?}`; `card_updated:true` is included for existing-character setting, worldbook or greeting updates. Changes, references, Outbox jobs and the request-fingerprinted receipt commit together; rollback removes only newly copied files. Identical token/request retries return the stored receipt. Changed requests, duplicate new-role names or deleted receipt targets return `409`; unknown assets `422`; missing/expired previews or missing targets `404`.
* `GET /characters/charx/previews/{token}/status` returns `{status,expires_at? ,result?}`. States: `parsing`, `ready`, `imported`, `cancelled`, `expired`, `not_found`, `target_deleted`. `imported` includes the committed result even after staged assets are removed or cancel is called; no request fingerprint is required to read the receipt. The upload response exposes a token only once parsing completes. The frontend queries status after a failed confirmation, freezes uncertain selections, and retries the original request snapshot rather than silently changing it. Definite validation failures with a ready preview permit correction.
* `charx_plan.py` explicitly maps supported CCv3 fields into the normalized card and compatibility report; it shares text normalization with existing cards. RisuAI modules, triggers, regex and module-contained lorebooks are never loaded. Inline images and variable interfaces are simplified with warnings. No automatic emotions/outfits/greetings behavior is restored. The separate PNG/JSON endpoints retain their existing HTTP contract.
* New characters keep the package worldbook. Existing-character updates preserve the name and, unless `sync_lorebook:true`, the worldbook. Explicit worldbook sync requires a nonempty valid embedded entries list, otherwise `422`. A selected alternate greeting swaps with the package first greeting before merging; explicit greeting selection updates the first and alternate greeting list even in keep/fill mode. Existing story messages are not rewritten.
* Temporary previews use `<system-temp>/ai-roleplay-charx-<database-path-hash>/<token>/` and are not public. Confirmed image files use `app.upload_avatar_dir/portrait_<uuid>.<format>`; character data, resource metadata and receipts persist in SQLite. Unselected package files are not permanently extracted. Portrait/character deletion queues Outbox cleanup and retains image files while another avatar/portrait still references them.
