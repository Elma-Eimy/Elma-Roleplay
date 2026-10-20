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
| **POST** | `/characters/translation-cache` | Read an existing Chinese reading copy without invoking a model |
| **POST** | `/characters/translate` | Translate reading fields and cache the Chinese copy separately |
| **POST** | `/characters/create` | Save new character to database |
| **GET** | `/characters` | Get abbreviated character list |
| **GET** | `/characters/{character_id}` | Get full details of a specific character |
| **GET** | `/characters/{character_id}/memory-overview` | Get paginated story memory navigation and statistics |
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
* Also returns `translation_model` (default `deepseek-flash`), independently selectable for character reading translations. It uses the existing chat connection; thinking is disabled when supported and enabled for fixed-reasoning models. Changing it does not discard existing translations; use `force: true` to refresh them.
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
* Uses `translation_model` and the existing chat provider connection. Long cards are segmented; the complete result is committed to SQLite atomically. Invalid/truncated model output, changed placeholders or translation service failures return `502`; the original card and previous successful cache are retained. Invalid request shapes return `422`.
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
| GET | (none) | `limit=10` (1–20), `offset=0` (≥0) | `{ "items": [Consolidation], "total": 12, "limit": 10, "offset": 0, "has_more": true }`, local records in descending ID order |
| POST | `/preview` | `{ "after_id": 0 }`, integer ≥ 0 | `Consolidation` |
| POST | `/{batch_id}/apply` | `{ "group_ids": [0] }`, 1–12 distinct non-negative indices | `Consolidation` |
| POST | `/{batch_id}/undo` | None | `Consolidation` |

`Consolidation` contains `id`, `status` (`preview/applied/undone`), `created_at`, `sources` (original-card snapshots), `groups` (`id`, `kind: duplicate/event`, `source_ids`, `content`, `reason`), `selected_group_ids`, `results` (`id`, `content`), `scanned_count`, `remaining_count`, `has_more`, and `next_after_id`.

Each preview scans at most 80 active local original cards in ID order. Inherited cards and consolidation outputs are excluded. Preview persists suggestions without changing memories; apply accepts only saved group indices, atomically revalidates unchanged sources, preserves originals, creates derived cards/source links/story scope, and queues vector Outbox tasks. Repeating the same apply/undo is idempotent. Selected originals enter the existing `superseded` category (UI: 历史原卡); active counts and retrieval use the same story view. Filters still run before pagination.

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
