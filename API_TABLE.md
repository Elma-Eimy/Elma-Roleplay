# AI Roleplay Backend API Documentation

This document describes the HTTP API endpoints provided by the backend for frontend integration.

This is the shared API reference for both `app-backend` and `app-frontend`.
See [Memory API details](docs/api/MEMORY_API.md) for memory filtering, statistics,
inheritance and story navigation rules, and the [documentation index](docs/README.md)
for component setup instructions. Configuration paths such as `.env` and
`config.yaml` in this reference are relative to `app-backend/`.

Reviewed against local routes and schemas on 2026-10-20. Response examples are
illustrative; configurable values depend on the running backend.

## 📌 Global Specifications

* **Base URL**: `http://127.0.0.1:8000`
* **Content-Type**: `application/json` (except file uploads)
* **Authentication**: Business API endpoints require the `X-API-Key` header when `ACCESS_API_KEY` is configured in `.env`. Public avatar files under `/assets/avatars/` are exempt; the built-in `/docs`, `/redoc`, and `/openapi.json` pages are also currently public.
  - Header: `X-API-Key: <your-secret>`
  - If `ACCESS_API_KEY` is empty (local dev), the header can be omitted.
  - Missing or wrong key returns `403 Forbidden`.
* **CORS**: Enabled for `GET`, `POST`, `PUT`, `DELETE`, `OPTIONS` methods and all headers.
* **Static Assets & Audio**: 
  - Uploaded avatars: `http://127.0.0.1:8000/assets/avatars/{filename}`
  - Synthesized speech: `http://127.0.0.1:8000/audio/{filename}` (requires the authentication header; see cache recovery limitations below)
  - Static asset URLs must be public or short-lived signed URLs. Clients must never put the long-lived API key in URL query parameters.

---

## 🗺️ API Endpoints Summary

### 1. General & Utilities
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **GET** | `/` | Service health status check |
| **POST** | `/upload/avatar` | Upload raw avatar image |
| **GET** | `/utils/settings` | Retrieve active customizable dialogue and retrieval settings |
| **PUT** | `/utils/settings` | Update customizable dialogue and retrieval settings (instant & persistent) |
| **POST** | `/utils/tts` | Synthesize speech from text (returns audio URL) |
| **GET** | `/audio/{filename}` | Download/play synthesized audio file; missing files may require a new TTS request |

### 2. Character Blueprint Management (`/characters`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/characters/parse` | Parse character card (PNG/JSON) without saving |
| **POST** | `/characters/charx/preview` | Validate a bounded CHARX/ZIP and stage a temporary preview |
| **GET** | `/characters/charx/previews/{token}/images` | Read a page of inline image thumbnails |
| **GET** | `/characters/charx/previews/{token}/status` | Recover preview state or a committed import receipt |
| **POST** | `/characters/charx/previews/{token}/cancel` | Discard a temporary preview |
| **POST** | `/characters/charx/previews/{token}/import` | Confirm an idempotent new-role, card/lorebook update or images-only import |
| **POST** | `/characters/translation-cache` | Read an existing Chinese reading copy without invoking a model |
| **POST** | `/characters/translate` | Translate reading fields and cache the Chinese copy separately |
| **POST** | `/characters/create` | Save new character to database |
| **GET** | `/characters` | Get abbreviated character list |
| **GET** | `/characters/{character_id}` | Get full details of a specific character |
| **GET** | `/characters/{character_id}/memory-overview` | Get paginated story memory navigation and statistics |
| **GET / POST** | `/characters/{character_id}/portraits` | List / upload optional portrait images |
| **PUT** | `/characters/{character_id}/portraits/{portrait_id}` | Rename a portrait |
| **POST** | `/characters/{character_id}/portraits/{portrait_id}/delete` | Delete a portrait and queue file cleanup |
| **PUT** | `/characters/{character_id}` | Update settings of an existing character |
| **DELETE** | `/characters/{character_id}` | Delete character and cascade wipe all sessions/memories |
| **POST** | `/characters/{character_id}/delete` | Alternative POST method for deletion (to avoid HTTP/HTTPS redirect downgrades) |

### 3. Session & Message Management (`/sessions`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/sessions/create` | Create a new session (fresh or inherited) |
| **GET** | `/sessions/recent` | Get paginated recent sessions with character and last-message summaries |
| **GET** | `/sessions` | List a character's sessions with last-message previews and pagination |
| **GET** | `/sessions/{session_id}` | Retrieve details of a session and its persona |
| **GET** | `/sessions/{session_id}/role-state` | Read branch-local current scene and per-character state |
| **GET / PUT** | `/sessions/{session_id}/portrait` | Read / manually select a portrait at the current story node |
| **PUT** | `/sessions/{session_id}/role-state` | Apply a manual state correction with optimistic revision checking |
| **GET** | `/sessions/{session_id}/history` | Get inheritance-aware chronological chat history (cursor pagination) |
| **PUT** | `/sessions/{session_id}/title` | Rename a session's title |
| **DELETE** | `/sessions/{session_id}` | Delete a session and safely relink children |
| **POST** | `/sessions/{session_id}/delete` | Alternative POST method for session deletion |
| **POST** | `/sessions/{session_id}/trigger_summary` | Manually extract memories from new messages |
| **POST** | `/sessions/{session_id}/trigger_cognition` | Manually update character micro-cognition |
| **PUT** | `/sessions/messages/{message_id}` | Edit content of a single message |
| **DELETE** | `/sessions/messages/{message_id}` | Delete a message (undo/rollback dialog state) |
| **POST** | `/sessions/messages/{message_id}/delete` | Alternative POST method for message deletion |
| **GET** | `/sessions/{session_id}/memories` | Filter and page visible memories with branch-aware category statistics |
| **POST** | `/sessions/{session_id}/memories` | Manually add a custom vector memory to this session |
| **PUT** | `/sessions/{session_id}/memories/{memory_id}` | Edit a local vector memory (inherited memories are read-only) |
| **DELETE** | `/sessions/{session_id}/memories/{memory_id}` | Delete a local vector memory (inherited memories are read-only) |
| **GET** | `/sessions/{session_id}/compile_prompt` | Preview the assembled prompt and its heuristic Token range/section breakdown |

### 4. World Book (Lorebook) Management (`/lorebooks`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/lorebooks/import` | Import and parse SillyTavern lorebook JSON file |
| **GET** | `/lorebooks` | List all independent lorebooks |
| **GET** | `/lorebooks/{lorebook_id}` | Retrieve a lorebook's details and all its entries |
| **PUT** | `/lorebooks/{lorebook_id}` | Update a lorebook's properties or its entry list |
| **DELETE** | `/lorebooks/{lorebook_id}` | Delete a lorebook and cascade remove bindings |
| **POST** | `/lorebooks/{lorebook_id}/delete` | Alternative POST method for lorebook deletion |
| **POST** | `/lorebooks/characters/{character_id}/bind/{lorebook_id}` | Bind a lorebook to a character |
| **POST** | `/lorebooks/characters/{character_id}/unbind/{lorebook_id}` | Unbind a lorebook from a character |

### 5. Conversations & Inference (`/chat`)

Both `/chat` and `/chat/stream` accept independent model settings, including regeneration. Supplying `model` or `thinking_mode` takes precedence over legacy `use_reasoning`. Invalid combinations fail with `400` before writing a user message. Story overrides are client-local; global defaults persist on the server. See [model settings](docs/MODEL_SELECTION.md).
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/chat` | Submit message, run RAG, compile prompt, write response (blocking) |
| **POST** | `/chat/stream` | Stream reply chunk-by-chunk using Server-Sent Events (SSE) |
| **POST** | `/chat/switch_candidate` | Switch active assistant message candidate version (recalculating affection/mood) |

---

## 📝 Detailed API Reference

### Current role state

`GET /sessions/{session_id}/role-state` returns `{session_id, revision, state}`. `revision` is a 64-character SHA-256 digest of the branch baseline and active message/state sequence. `state` contains optional `scene` and `characters`, where character names map to optional `posture`, `clothing`, and `location` strings. Unknown fields may be absent; an explicitly cleared scene is `null` and does not restore the opening location.

`PUT /sessions/{session_id}/role-state` accepts:

```json
{
  "expected_revision": "<64-character revision from GET>",
  "patch": {
    "scene": "客厅",
    "characters": {"露娜": {"posture": "坐在沙发上", "clothing": "白色衬衫", "location": "窗边"}}
  }
}
```

- Returns the updated GET shape. Omitted fields remain unchanged; manual `null` or empty string clears a field. Clearing all known fields removes that character's state. Scene limit: 300 characters; character names: 1–50 characters; posture/clothing/location: 1–200 characters; at most 8 characters in the resulting state. Up to 16 character entries are allowed in a manual patch to clear old entries while adding new ones. Unknown keys, invalid types, oversized payloads or invalid revisions return `422`.
- Missing session/persona returns `404`. A stale revision or a session currently generating a reply returns `409`. Corrections attach to the latest active local message, or the baseline when no messages exist, and affect subsequent prompt assembly. Reads do not call an LLM.
- Chat generation must append an increment such as `<state_update>{"scene":"客厅","characters":{"露娜":{"posture":"站着"}}}</state_update>` after reply/status when state changes or is first explicitly described; the entire increment may be omitted when nothing changes. This is an internal model-output protocol, not an extra SSE event. Only changed or first explicitly described fields are emitted; omitted updates preserve state. LLM patches cannot clear fields or use nulls. Invalid patches are ignored atomically while reply/status are retained; raw state tags never enter stored reply text or streamed body chunks.
- Active candidates determine state. Regeneration starts before the replaced candidate; branches snapshot only their selected message boundary. Editing assistant text invalidates that message's model-derived patch, preserving manual corrections. Existing emotion/affection behavior remains separate. See [role-state behavior](docs/ROLE_STATE.md) for scope and limitations.

### 1. General & Utilities

#### GET `/`
* **Response (200 OK)**:
  ```json
  {
    "status": "Core Engine is running"
  }
  ```

#### POST `/upload/avatar`
* **Request**: `multipart/form-data`
  - `file`: Binary image file (PNG/JPG/JPEG/WEBP). Size is limited by `app.max_card_size_mb` in `config.yaml` (schema default: 10 MB); larger uploads return `413`.
* **Response (200 OK)**:
  ```json
  {
    "message": "Avatar uploaded successfully",
    "avatar_path": "assets/avatars/4a6b2c8d_helper.png"
  }
  ```

#### GET `/utils/settings`
* Also returns `translation_model`, independently selectable for character reading translations. When absent, it initializes once from the existing non-reasoning chat model (falling back to the legacy chat model or default chat model). It uses the existing chat connection; thinking is disabled when supported and enabled for fixed-reasoning models. Changing it does not discard existing translations; use `force: true` to refresh them.
* Also returns `default_chat_model`, `model_profiles` (editable `{id,label,adapter}` entries), `model_catalog` (read-only `{id,label,adapter,thinking,efforts}` capabilities), `memory_model`, `memory_thinking_mode`, `memory_reasoning_effort`, `tts_preprocess_model`, `tts_thinking_mode`, and `tts_reasoning_effort`.
* `thinking` is `toggle`, `always`, or `unsupported`. Adapters: `compatible`, `deepseek`, `reasoning`. The catalog is configured locally; it does not query providers.
* **Response (200 OK)**:
  ```json
  {
    "temperature": 0.7,
    "reasoning_mode": false,
    "context_history_limit": 15,
    "retrieval_top_k": 3,
    "retrieval_context_turns": 3,
    "retrieval_query_max_chars": 2400,
    "retrieval_min_importance": 0.3,
    "retrieval_max_distance": 1.2,
    "lorebook_scan_depth": 5,
    "lorebook_token_budget": 3000,
    "lorebook_max_recursive_passes": 3,
    "cognition_max_words": 200,
    "retrieval_half_life_turns": 50,
    "retrieval_candidate_multiplier": 3,
    "max_tokens": 4096,
    "top_p": 1.0,
    "presence_penalty": 0.0,
    "frequency_penalty": 0.0,
    "repetition_penalty": 1.0,
    "reasoning_effort": "high"
  }
  ```

#### PUT `/utils/settings`
* `translation_model` accepts a nonblank model ID (up to 200 characters), independently of chat, memory and TTS settings.
* Accepts the additional GET fields above except read-only `model_catalog`. Auxiliary thinking modes are `enabled`/`disabled`; effort is a supported string. `reasoning_effort: null` resets the global effort to the provider default. Model IDs must be nonblank and profile IDs unique.
* `reasoning_mode` controls thinking independently of `default_chat_model`. Invalid model/thinking/effort combinations return `400` before persistence; malformed fields return `422`.
* **Supported fields**: Only fields declared by `app-backend/schemas.py::SettingsUpdate` are accepted. Retrieval scoring weights, ancestor weight, deduplication threshold, and graph thresholds are not exposed by this HTTP API; edit YAML and restart for those settings. `memory_handoff_margin` is accepted by PUT but is not currently included in the GET response.
* **Request (JSON)**: *(All fields optional)*
  ```json
  {
    "temperature": 0.5,
    "reasoning_mode": true,
    "context_history_limit": 20,
    "retrieval_top_k": 5,
    "reasoning_effort": "medium"
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "message": "Settings updated and persisted successfully",
    "updated": {
      "temperature": 0.5,
      "reasoning_mode": true,
      "context_history_limit": 20,
      "retrieval_top_k": 5,
      "reasoning_effort": "medium"
    }
  }
  ```

#### POST `/utils/tts`
* **Request (JSON)**:
  ```json
  {
    "message_id": 12,       // Optional: Associate with a database message
    "text": "你好呀，很高兴认识你！",
    "voice": "冰糖",        // Optional: voice name
    "speed": 1.0           // Optional: default 1.0
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "audio_url": "/audio/msg_12_p2_冰糖_1.00.mp3"
  }
  ```

#### GET `/audio/{filename}`
* **Response (200 OK)**: Binary audio stream (typically MP3/WAV format).
  - *Current limitation*: The download route only recognizes legacy `msg_{id}_{voice}_{speed}.mp3` names for recovery, while the TTS service now generates `msg_{id}_p2_{voice}_{speed}.mp3`. Missing versioned files therefore return `404` on direct download. Request `POST /utils/tts` with the original `message_id` and matching voice/speed to regenerate the file and use the returned URL. Plain-text hash files cannot be regenerated from the download URL alone.

---

### 2. Character Blueprint Management (`/characters`)

#### POST `/characters/parse`
* **Request**: `multipart/form-data`
  - `file`: PNG Character Card containing SillyTavern metadata (tEXt/zTXt/iTXt) or standard JSON config file.
* **Storage**: Parsing does not create a database record. Valid PNGs are retained as content-addressed avatars; identical uploads reuse the same path. Clients should use the returned `avatar_path` without uploading the image again. JSON uploads and failed parses are temporary and leave no avatar file. With multiple valid `chara` chunks, the first is used. See [character card compatibility](docs/CHARACTER_CARDS.md).
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

#### POST `/characters/translation-cache`
* **Request (JSON)**: `{ "card": { "name": "Traveler", "description": "English background", "first_mes": "Hello {{user}}", "extensions": { "alternate_greetings": ["", "Another greeting"] } } }`.
* `card` accepts the same source fields as character creation; only `description`, `personality`, `scenario`, `first_mes`, `mes_example`, `creator_notes`, and `extensions.alternate_greetings` form the cache key. Unknown/non-string alternate items normalize to empty strings without shifting indexes.
* **Response (200)**: `{ "translation": null }` on a miss; on a hit returns the same translation object as `/characters/translate`. This endpoint never invokes a model or creates a character. Reading content above 120,000 characters returns `400`.

#### POST `/characters/translate`
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

#### POST `/characters/create`
* **Duplicate handling**: The response includes `created: true` for a new record, or `created: false` with the existing `character_id` and `name` for an existing exact name. The latter does not apply the submitted settings. Clients must prompt the user instead of silently opening a story with the old card.
* **Request (JSON)**:
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

#### GET `/characters`
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

#### GET `/characters/{character_id}`
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

#### GET `/characters/{character_id}/memory-overview`
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

#### PUT `/characters/{character_id}`
* **Request (JSON)**: Same format as `POST /characters/create`.
* **Response (200 OK)**:
  ```json
  {
    "message": "Character updated successfully",
    "character_id": 1,
    "name": "测试小助手"
  }
  ```

#### DELETE `/characters/{character_id}` (or POST `/characters/{character_id}/delete`)
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

### 3. Session & Message Management (`/sessions`)

#### Manual character portraits

`GET /characters/{character_id}/portraits` is paginated: optional `offset` (default 0) and `limit` (default 24, maximum 100), with additional `total` and `has_more` response fields. Imported portraits may also contain `source_type`, `source_name` and `source_uri`; manual portraits omit empty provenance fields.

* `GET /characters/{character_id}/portraits` returns `{ "portraits": [{ "id": 1, "name": "便服", "image_path": "assets/avatars/portrait_....png" }] }`, ordered by ID. A plain character returns an empty list.
* `POST /characters/{character_id}/portraits` accepts multipart `file`, verifies PNG/JPEG/WebP content and pixel decoding, the configured `SECURITY_MAX_CARD_SIZE_MB` limit and at most 25 million pixels. Returns the saved portrait object; invalid or truncated images return `422`, oversized uploads `413`, missing characters `404`. This upload attaches the resource immediately; failure before database commit removes the newly written file.
* `PUT /characters/{character_id}/portraits/{portrait_id}` accepts `{ "name": "便服" }` (trimmed, 1–80 characters, no control characters). Returns the portrait object. Names carry no automatic emotion or story meaning.
* `POST /characters/{character_id}/portraits/{portrait_id}/delete` returns `{ "message": "..." }`. Resources are shared by all stories of that character. Referencing stories fall back to the character avatar; cleanup uses Outbox and checks both avatar and portrait references. Missing or foreign portraits return `404`.
* `GET /sessions/{session_id}/portrait` returns `{ "session_id": 1, "portrait_id": null, "image_path": "avatar.png", "revision": "<64 hex characters>" }`. `null` means avatar fallback, including removed resources.
* `PUT /sessions/{session_id}/portrait` accepts `{ "portrait_id": 1, "expected_revision": "<revision from GET>" }`; explicit `null` restores avatar fallback. Returns the same shape as GET. A stale revision or active generation returns `409`; missing/foreign resources or invalid payloads return `422`; missing stories return `404`.
* Selections apply after the current latest active message (or the empty story baseline), persist across devices, and replay only active local messages. Regeneration and candidate switching restore that candidate's selection; forks snapshot the selected message boundary, including a nonactive candidate, without reading later parent changes. An empty parent story passes its portrait baseline to the new branch as an independent snapshot. Deleting a selection's message removes that override. The image ID is never reused after deletion.
* This version has no required tags, emotion classification, outfit groups or greeting bindings. Pure/character background mode remains a separate client preference; selecting an image does not turn on character background mode.

#### Conservative CHARX import

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

#### POST `/sessions/create`
* **Request (JSON)**:
  ```json
  {
    "character_id": 1,
    "parent_session_id": null, // Pass an integer to fork from a parent session, or null for a fresh timeline
    "title": "测试对话 1",
    "greeting_index": null,    // Optional: Select candidate greeting index
    "start_message_id": null   // Optional: Set specific starting message node
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

#### GET `/sessions`
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

#### GET `/sessions/recent`
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

#### GET `/sessions/{session_id}`
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

#### GET `/sessions/{session_id}/history`
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

#### PUT `/sessions/{session_id}/title`
* **Request (JSON)**:
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

#### DELETE `/sessions/{session_id}` (or POST `/sessions/{session_id}/delete`)
* **Response (200 OK)**:
  ```json
  {
    "message": "Session deleted successfully",
    "deleted_session_id": 1,
    "relinked_children": 1,
    "memories_deleted": 2
  }
  ```

#### POST `/sessions/{session_id}/trigger_summary`
* **Response (200 OK)**:
  ```json
  {
    "message": "记忆提纯流程已完成",
    "session_id": 1,
    "extracted_count": 3
  }
  ```

#### POST `/sessions/{session_id}/trigger_cognition`
* **Response (200 OK)**:
  ```json
  {
    "message": "认知更新已完成",
    "session_id": 1,
    "cognition_state": "角色当前的新认知文本..."
  }
  ```

#### PUT `/sessions/messages/{message_id}`
* **Request (JSON)**:
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

#### DELETE `/sessions/messages/{message_id}` (or POST `/sessions/messages/{message_id}/delete`)
* **Response (200 OK)**:
  ```json
  {
    "message": "Message deleted successfully",
    "message_id": 1
  }
  ```

#### GET `/sessions/{session_id}/memories`
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

#### POST `/sessions/{session_id}/memories`
* **Request (JSON)**:
  ```json
  {
    "content": "这是一家开在转角处的日式猫咪咖啡厅，环境清静舒适。",
    "importance_score": 0.9,     // Optional, defaults to 0.8
    "memory_type": "fact"        // Optional: event, emotion, relationship, fact
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

#### PUT `/sessions/{session_id}/memories/{memory_id}`
* **Request (JSON)**:
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

#### DELETE `/sessions/{session_id}/memories/{memory_id}`
* **Response (200 OK)**:
  ```json
  {
    "message": "Memory deleted successfully",
    "memory_id": 5
  }
  ```

#### Memory consolidation (`/sessions/{session_id}/memory-consolidations`)

| Method | Path suffix | Request | Response |
| --- | --- | --- | --- |
| GET | (none) | `limit=10` (1–20), `offset=0` (≥0) | `{ "items": [Consolidation], "total": 12, "limit": 10, "offset": 0, "has_more": true, "scan_status": ScanStatus }`, local records in descending ID order |
| POST | `/preview` | `{ "after_id": 0, "mode": "full" }`; mode is `full` (default) or `incremental`; incremental requires after_id=0 | `Consolidation` |
| POST | `/{batch_id}/apply` | `{ "group_ids": [0], "expected_revision": 0 }`, 1–12 distinct non-negative indices | `Consolidation` |
| PUT | `/{batch_id}/groups/{group_id}` | `{ "expected_revision": 0, "content": "Reviewed content", "ignored": false, "ignore_reason": "" }` | `Consolidation` |
| POST | `/{batch_id}/undo` | None | `Consolidation` |

`Consolidation` contains `id`, `status` (`preview/applied/undone`), `created_at`, `sources` (original-card snapshots), `groups` (`id`, `kind: duplicate/event`, `source_ids`, `content`, `reason`), `selected_group_ids`, `results` (`id`, `content`), `scanned_count`, `remaining_count`, `has_more`, and `next_after_id`.

Source snapshots may additionally carry `temporal_status` (`unknown/current/historical/planned`) and `temporal_note` (string or null); legacy records may omit them. Preview and apply reject groups mixing story-time statuses or notes; summaries preserve matching values. Chat semantic and graph recall share SQLite fact IDs, story/fork cutoffs, deduplication and a joint budget; consolidated originals map to active summaries. New automatic-card message fingerprints are revalidated before injection; legacy/manual cards without snapshots retain compatibility. Ordinary memory-list fields and counts are unchanged.

Manual scan modes: `full` scans eligible originals after the ID cursor regardless of earlier checks; `incremental` scans only originals whose current fingerprint has not been checked, including changed low-ID cards, and continues with after_id=0. Neither mode clusters across batches or adds previously checked cards to incremental input. Successful model responses (including empty suggestions) atomically save the preview and unchanged source fingerprints. Failures do not advance progress; edits/deletions during model generation are not recorded as checked. With fewer than two sources, no model is called and no card is marked checked. Apply/undo does not reset checked versions. Existing previews remain intact on upgrade; their old scan progress is not inferred.

If any source of a suggested group changes or becomes ineligible during generation, this scan also defers the remaining sources of that group so a later incremental scan can retry together. Other valid groups advance normally; records from newer successful scans are preserved.

New record fields: `scan_mode` (legacy default `full`), `model_checked` (whether at least two cards were sent and the response validated), `recorded_count` (unchanged source versions recorded this time). `remaining_count` is the number of cards in the requested scope before this batch. Full-mode `has_more` follows the ID cursor; incremental `has_more` means at least two pending cards remain at save time. One pending card waits for another or for a later manual full scan. `ScanStatus` contains current `eligible_count`, `checked_count`, `pending_count`; list GET returns it once at the top level, while individual POST/PUT responses include `scan_status`. Counts cover only active local ordinary cards, excluding inherited/hidden originals and summaries. Checked does not mean reviewed or applied; saved suggestions remain available through history. Progress uses SQLite `memory_consolidation_scans`, not ChromaDB; the internal fingerprint is not exposed over HTTP.

Review adds batch `review_revision` (legacy records default to 0) and group `original_content`, `ignored`, `ignore_reason`, `conflict` (message or null). PUT is allowed only for previews: optional trimmed content is 4–500 characters, reason is at most 160 characters, ignored defaults to false. Omit content to change only review metadata, including on stale groups. Each save increments the revision; stale revisions return 409. Apply defaults its expected revision to 0 for older clients, uses saved reviewed content, and rejects ignored or conflicting selected groups. Unselected conflicts do not block valid groups. Ignore is limited to this preview and can be reversed before apply; it does not suppress future previews. Review preserves model originals and source snapshots in the existing JSON record, without memory/vector writes or a schema migration. Generation locks also block review saves.

Each preview scans at most 100 active local original cards in ID order. Inherited cards and consolidation outputs are excluded. Preview persists suggestions without changing memories; apply accepts only saved group indices, atomically revalidates unchanged sources, preserves originals, creates derived cards/source links/story scope, and queues vector Outbox tasks. Repeating the same apply/undo is idempotent. Selected originals enter the existing `superseded` category (UI: 历史原卡); active counts and retrieval use the same story view. Filters still run before pagination.

Preview omits an entire suggested group when its event sources contain conflicting explicit occurrence dates; safe groups remain selectable and omitted sources remain active. Apply rechecks the same boundary, including previously saved previews, returning `409` on conflict. Appointment/plan target dates are not treated as occurrence dates. This conservative guard recognizes numeric Chinese calendar dates, `YYYY-MM-DD`/`YYYY/MM/DD`, and explicit years; it does not resolve relative dates or guarantee semantic event identity.

For `duplicate` suggestions, sources with differing explicit negation markers are also omitted and rechecked on apply. This favors keeping originals over combining positive/negative facts; absence of a recognized marker does not prove semantic equivalence, and differently phrased equivalent facts may conservatively remain separate.

Forks copy enabled consolidation scopes with at least one group visible at creation and respect source-message cutoffs; later parent apply/undo does not change existing children. Sources referenced by actually visible consolidation groups and derived outputs are read-only (`409` for ordinary edit/delete); invisible legacy scope associations do not lock originals. Undo restores originals only in the current story and retains referenced outputs for existing forks. Subsequent replacements visible in the current story block undo with `409`; child-only replacements do not prevent parent undo. Graph/cognition/message state is unchanged.

Source-message foreign-key references may become `null` after deletion. An internal persistent source upper bound still enforces branch isolation for original cards and derived summaries; HTTP response fields are unchanged. Upgrade restores known cutoffs from existing references and saved consolidation snapshots where available. Truly manual cards without message provenance retain their inheritance behavior.

Errors: `404` for missing story/local record; `422` for invalid request; `409` for changed sources, conflicting state or apply/undo during generation; `502` for failed/invalid model suggestions. Full payload/lifecycle rules: [Memory API](docs/api/MEMORY_API.md#可预览的存量记忆整理). New vectors synchronize asynchronously; recall may temporarily omit results until Outbox upsert completes.

#### GET `/sessions/{session_id}/compile_prompt`
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

### 4. World Book (Lorebook) Management (`/lorebooks`)

#### POST `/lorebooks/import`
* **Request**: `multipart/form-data`
  - `file`: JSON file in SillyTavern lorebook format.
* **Response (200 OK)**:
  ```json
  {
    "message": "Lorebook imported successfully",
    "lorebook_id": 1,
    "name": "魔法学院设定集",
    "entries_count": 28
  }
  ```

#### GET `/lorebooks`
* **Response (200 OK)**:
  ```json
  {
    "lorebooks": [
      {
        "id": 1,
        "name": "魔法学院设定集",
        "description": "学院的历史、老师与禁忌设定集",
        "scan_depth": 5,
        "token_budget": 3000,
        "recursive_scanning": true,
        "entries_count": 28,
        "created_at": "2026-05-23T16:00:19"
      }
    ]
  }
  ```

#### GET `/lorebooks/{lorebook_id}`
* **Response (200 OK)**:
  ```json
  {
    "id": 1,
    "name": "魔法学院设定集",
    "description": "学院的历史...",
    "scan_depth": 5,
    "token_budget": 3000,
    "recursive_scanning": true,
    "entries": [
      {
        "keys": ["学院", "魔法学院"],
        "content": "魔法学院创立于西历120年，是一座历史悠久的建筑...",
        "enabled": true,
        "constant": false,
        "case_sensitive": false,
        "selective": false,
        "secondary_keys": [],
        "position": "before_char",
        "insertion_order": 100
      }
    ],
    "created_at": "2026-05-23T16:00:19"
  }
  ```

#### PUT `/lorebooks/{lorebook_id}`
* **Request (JSON)**: *(All fields optional)*
  ```json
  {
    "name": "更新设定集名称",
    "description": "更新后的描述",
    "scan_depth": 8,
    "token_budget": 4000,
    "recursive_scanning": false,
    "entries": [
      {
        "keys": ["魔法师"],
        "content": "本世界的魔法师等级分为初级、中级、高级...",
        "enabled": true,
        "constant": false,
        "case_sensitive": false,
        "selective": false,
        "secondary_keys": [],
        "position": "before_char",
        "insertion_order": 100
      }
    ]
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "message": "Lorebook updated successfully",
    "lorebook_id": 1,
    "name": "更新设定集名称",
    "entries_count": 1
  }
  ```

#### DELETE `/lorebooks/{lorebook_id}` (or POST `/lorebooks/{lorebook_id}/delete`)
* **Response (200 OK)**:
  ```json
  {
    "message": "Lorebook deleted successfully",
    "lorebook_id": 1
  }
  ```

#### POST `/lorebooks/characters/{character_id}/bind/{lorebook_id}`
* **Response (200 OK)**:
  ```json
  {
    "message": "Successfully bound lorebook '魔法学院设定集' to character '爱丽丝'",
    "character_id": 1,
    "lorebook_id": 1
  }
  ```

#### POST `/lorebooks/characters/{character_id}/unbind/{lorebook_id}`
* **Response (200 OK)**:
  ```json
  {
    "message": "Successfully unbound lorebook '魔法学院设定集' from character '爱丽丝'",
    "character_id": 1,
    "lorebook_id": 1
  }
  ```

---

### 5. Conversations & Inference (`/chat`)

Both `/chat` and `/chat/stream` accept independent model settings, including regeneration. Supplying `model` or `thinking_mode` takes precedence over legacy `use_reasoning`. Invalid combinations fail with `400` before writing a user message. Story overrides are client-local; global defaults persist on the server. See [model settings](docs/MODEL_SELECTION.md).

#### POST `/chat`
* **Request (JSON)**:
  ```json
  {
    "session_id": 1,
    "user_message": "你好呀，爱丽丝",
    "model": "deepseek-flash",  // Optional: independent model; omitted = global default
    "thinking_mode": "enabled", // Optional: inherit / enabled / disabled
    "reasoning_effort": "max", // Optional: inherits global effort when omitted
    "use_reasoning": null,      // Legacy clients only: selects old reasoning/non-reasoning slots
    "is_regenerate": false,     // Optional: set true to regenerate the assistant response of the current turn
    "user_nickname": "用户",    // Optional: user nickname injected into the prompt
    "temperature": null,        // Optional parameter overrides
    "top_p": null,
    "presence_penalty": null,
    "frequency_penalty": null,
    "repetition_penalty": null
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "reply": "你好呀！今天想聊些什么？",
    "emotion_tag": "开心",
    "affection_change": 1,
    "affection_score": 11,
    "model_used": "deepseek-v4-flash",
    "user_message_id": 4,
    "assistant_message_id": 5,
    "candidates": [
      {
        "id": 5,
        "content": "你好呀！今天想聊些什么？",
        "reasoning_content": null,
        "emotion_tag": "开心",
        "affection_change": 1,
        "created_at": "2026-05-23T16:05:00",
        "audio_path": null
      }
    ],
    "active_index": 0
  }
  ```

#### POST `/chat/stream`
* **Request (JSON)**: Same structure as `POST /chat`.
* **Disconnection & Background Persistence**: The model generation and database persistence lifecycle is decoupled from the HTTP transport connection. If the client disconnects or leaves the session during streaming, the background worker continues to consume the stream, persists the final assistant message and affection updates, and releases the session lock once complete.
* **Response (SSE Stream)**: `text/event-stream`
  - Yields reasoning/thinking steps (if reasoning is active):
    `data: {"reasoning_chunk": "爱丽丝听到用户的问候，决定开心地回应。"}`
  - Yields incremental reply chunks:
    `data: {"chunk": "你好"}`
    `data: {"chunk": "呀！"}`
  - Yields final metadata structure once generation completes:
    `data: {"emotion_tag": "开心", "affection_change": 1, "affection_score": 11, "model_used": "deepseek-v4-flash", "user_message_id": 4, "assistant_message_id": 5, "candidates": [...], "active_index": 0}`
  - Terminates with:
    `data: [DONE]`

#### POST `/chat/switch_candidate`

Only candidates belonging to the latest active user message can be switched.
Sending the next user message confirms and freezes the previous turn; changing an
earlier confirmed turn requires creating a session branch.

* **Request (JSON)**:
  ```json
  {
    "message_id": 6     // The assistant message ID you want to set as active
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "message": "Candidate switched successfully",
    "message_id": 6,
    "is_active": true,
    "affection_score": 12,
    "current_mood": "温柔"
  }
  ```
