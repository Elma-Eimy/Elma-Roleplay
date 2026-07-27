# AI Roleplay Backend API Documentation

This document describes the HTTP API endpoints provided by the backend for frontend integration.

## 📌 Global Specifications

* **Base URL**: `http://127.0.0.1:8000`
* **Content-Type**: `application/json` (except file uploads)
* **Authentication**: API endpoints and `/audio/{filename}` require the `X-API-Key` header when `ACCESS_API_KEY` is configured in `.env`. `/assets/avatars/{filename}` is the explicit public exception.
  - Header: `X-API-Key: <your-secret>`
  - If `ACCESS_API_KEY` is empty (local dev), the header can be omitted.
  - Missing or wrong key returns `403 Forbidden`.
* **CORS**: Enabled for `GET`, `POST`, `PUT`, `DELETE` methods and all headers.
* **Static Assets & Audio**: 
  - Uploaded avatars: `http://127.0.0.1:8000/assets/avatars/{filename}` — public static resource; no API key in either headers or URL.
  - Synthesized speech: `http://127.0.0.1:8000/audio/{filename}` — protected resource; clients must send `X-API-Key` in the request header. Supports automatic on-demand recovery and rebuilding if the physical file is lost.
  - Clients must never put the long-lived API key in URL query parameters.

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
| **GET** | `/audio/{filename}` | Download/play synthesized audio file (with self-healing) |

### 2. Character Blueprint Management (`/characters`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/characters/parse` | Parse character card (PNG/JSON) without saving |
| **POST** | `/characters/create` | Save new character to database |
| **GET** | `/characters` | Get abbreviated character list |
| **GET** | `/characters/{character_id}` | Get full details of a specific character |
| **PUT** | `/characters/{character_id}` | Update settings of an existing character |
| **DELETE** | `/characters/{character_id}` | Delete character and cascade wipe all sessions/memories |
| **POST** | `/characters/{character_id}/delete` | Alternative POST method for deletion (to avoid HTTP/HTTPS redirect downgrades) |

### 3. Session & Message Management (`/sessions`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/sessions/create` | Create a new session (fresh or inherited) |
| **GET** | `/sessions/recent` | Get paginated recent sessions with character and last-message summaries |
| **GET** | `/sessions` | List sessions associated with a character |
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
| **GET** | `/sessions/{session_id}/memories` | List all vector memories available to this session (including inherited ones) |
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
  - `file`: Binary image file (PNG/JPG/WEBP, ≤5MB)
* **Response (200 OK)**:
  ```json
  {
    "message": "Avatar uploaded successfully",
    "avatar_path": "assets/avatars/4a6b2c8d_helper.png"
  }
  ```

#### GET `/utils/settings`
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
    "audio_url": "/audio/msg_12_冰糖_1.0.mp3"
  }
  ```

#### GET `/audio/{filename}`
* **Authentication**: Send `X-API-Key` in the request header when `ACCESS_API_KEY` is configured. Query-string credentials are not supported.
* **Response (200 OK)**: Binary audio stream (typically MP3/WAV format).
  - *Note*: If the file doesn't exist on disk but corresponds to an existing database message ID in the name, the system will trigger a self-healing process to rebuild the audio file on the fly before returning it.

---

### 2. Character Blueprint Management (`/characters`)

#### POST `/characters/parse`
* **Request**: `multipart/form-data`
  - `file`: PNG Character Card containing SillyTavern metadata (tEXt/zTXt/iTXt) or standard JSON config file.
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

#### POST `/characters/create`
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
  - `limit`: Optional pagination limit
  - `offset`: Optional pagination offset
* **Response (200 OK)**:
  ```json
  {
    "character_id": 1,
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
        }
      }
    ]
  }
  ```

#### GET `/sessions/recent`
* **Purpose**: Home-screen aggregate endpoint. The backend should fetch sessions, character summaries, and each session's latest active message in one database query (or a bounded query set) to avoid client-side N+1 requests.
* **Query Parameters**:
  - `limit`: Optional pagination limit (frontend default: `50`)
  - `offset`: Optional pagination offset (default: `0`)
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
    "offset": 0
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
    ]
  }
  ```

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
  - `q`: Optional search keyword.
  - `limit`: Pagination limit (default 20).
  - `offset`: Pagination offset (default 0).
* **Response (200 OK)**:
  ```json
  [
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
  ]
  ```

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

#### PUT `/sessions/{session_id}/memories/{memory_id}`
* **Request (JSON)**:
  ```json
  {
    "content": "修改后的记忆文本内容",
    "importance_score": 0.8
  }
  ```
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
        "character": {"characters": 8200, "estimated_tokens": 6100, "lower_bound": 4800, "upper_bound": 7600}
      }
    }
  }
  ```
  `sections` always includes all documented prompt sections, including zero-valued ones. See `NEW_API.md` for the complete additive contract and estimation caveats.

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

#### POST `/chat`
* **Request (JSON)**:
  ```json
  {
    "session_id": 1,
    "user_message": "你好呀，爱丽丝",
    "use_reasoning": null,      // Optional: true, false or null (follows config reasoning_mode)
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
