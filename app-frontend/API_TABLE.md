# AI Roleplay Backend API Documentation

This document describes the HTTP API endpoints provided by the backend for frontend integration.

## 📌 Global Specifications

* **Base URL**: `http://127.0.0.1:8000`
* **Content-Type**: `application/json` (except file uploads)
* **Authentication**: All endpoints require the `X-API-Key` header when `ACCESS_API_KEY` is configured in `.env`.
  - Header: `X-API-Key: <your-secret>`
  - If `ACCESS_API_KEY` is empty (local dev), the header can be omitted.
  - Missing or wrong key returns `403 Forbidden`.
* **CORS**: Enabled for `GET`, `POST`, `PUT`, `DELETE` methods and all headers.
* **Static Assets**: Uploaded avatars are served at `http://127.0.0.1:8000/assets/avatars/{filename}`.

---

## 🗺️ API Endpoints Summary

### 1. General & Utilities
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **GET** | `/` | Service health status check |
| **POST** | `/upload/avatar` | Upload raw avatar image |
| **GET** | `/utils/settings` | Retrieve active customizable dialogue and retrieval settings |
| **PUT** | `/utils/settings` | Update customizable dialogue and retrieval settings (instant & persistent) |

### 2. Character Blueprint Management (`/characters`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/characters/parse` | Parse character card (PNG/JSON) without saving |
| **POST** | `/characters/create` | Save new character to database |
| **GET** | `/characters` | Get abbreviated character list |
| **GET** | `/characters/{character_id}` | Get full details of a specific character |
| **PUT** | `/characters/{character_id}` | Update settings of an existing character |
| **DELETE** | `/characters/{character_id}` | Delete character and cascade wipe all sessions/memories |

### 3. Session & Message Management (`/sessions`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/sessions/create` | Create a new session (fresh or inherited) |
| **GET** | `/sessions` | List sessions associated with a character |
| **GET** | `/sessions/{session_id}` | Retrieve details of a session and its persona |
| **GET** | `/sessions/{session_id}/history` | Get inheritance-aware chronological chat history |
| **PUT** | `/sessions/{session_id}/title` | Rename a session's title |
| **DELETE** | `/sessions/{session_id}` | Delete a session and safely relink children |
| **POST** | `/sessions/{session_id}/trigger_summary` | Manually extract memories from new messages |
| **POST** | `/sessions/{session_id}/trigger_cognition` | Manually update character micro-cognition |
| **PUT** | `/sessions/messages/{message_id}` | Edit content of a single message |
| **DELETE** | `/sessions/messages/{message_id}` | Delete a message (undo/rollback dialog state) |

### 4. Conversations (`/chat`)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/chat` | Submit message, run RAG, compile prompt, write response |

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
  - `file`: Binary image file (e.g. `helper.png`)
* **Response (200 OK)**:
  ```json
  {
    "message": "Avatar uploaded successfully",
    "avatar_path": "./assets/avatars/helper.png"
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
    "retrieval_min_importance": 0.3,
    "retrieval_max_distance": 1.2,
    "lorebook_scan_depth": 5,
    "lorebook_token_budget": 3000,
    "lorebook_max_recursive_passes": 3,
    "cognition_max_words": 200
  }
  ```

#### PUT `/utils/settings`
* **Request (JSON)**:
  *(Note: All fields are optional. Only supplied fields will be updated)*
  ```json
  {
    "temperature": 0.5,
    "reasoning_mode": true,
    "context_history_limit": 20,
    "retrieval_top_k": 5
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
      "retrieval_top_k": 5
    }
  }
  ```

---

### 2. Character Blueprint Management (`/characters`)

#### POST `/characters/parse`
* **Request**: `multipart/form-data`
  - `file`: PNG Character Card or V1/V2 JSON file.
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
      "avatar_path": "./assets/avatars/helper.png"
    }
  }
  ```

#### POST `/characters/create`
* **Request (JSON)**:
  ```json
  {
    "name": "测试小助手",
    "avatar_path": "./assets/avatars/helper.png",
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
* **Response (200 OK)**:
  ```json
  {
    "characters": [
      {
        "id": 1,
        "name": "测试小助手",
        "avatar_path": "./assets/avatars/helper.png",
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
    "avatar_path": "./assets/avatars/helper.png",
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
    "name": "测试小助手_已更新"
  }
  ```

#### DELETE `/characters/{character_id}`
* **Response (200 OK)**:
  ```json
  {
    "message": "Character and all associated sessions/memories deleted successfully",
    "character_id": 1,
    "sessions_deleted_count": 2
  }
  ```

---

### 3. Session & Message Management (`/sessions`)

#### POST `/sessions/create`
* **Request (JSON)**:
  ```json
  {
    "character_id": 1,
    "parent_session_id": null, // 传入 int 则为从父会话继承分支，null 则为全新会话
    "title": "测试对话 1"
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
* **Request Query Parameters**:
  - `character_id`: Filter sessions by Character ID (Required)
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
      "cognition_state": "当前角色认识摘要...",
      "current_mood": "平静",
      "current_scenario_override": "学校"
    },
    "character": {
      "id": 1,
      "name": "测试小助手",
      "avatar_path": "./assets/avatars/helper.png"
    }
  }
  ```

#### GET `/sessions/{session_id}/history`
* **Request Query Parameters**:
  - `limit`: Maximum number of messages to retrieve (Default: 50)
* **Response (200 OK)**:
  *(Note: Messages are returned in strict chronological order. It walks up the parent sessions to backfill history if the current session is inherited)*
  ```json
  {
    "session_id": 1,
    "messages": [
      {
        "id": 1,
        "role": "assistant",
        "content": "你好呀！有什么我可以帮你的吗？",
        "emotion_tag": "平静",
        "affection_change": 0,
        "created_at": "2026-05-23T16:00:19"
      },
      {
        "id": 2,
        "role": "user",
        "content": "你好，我想写一段Python代码。",
        "emotion_tag": null,
        "affection_change": null,
        "created_at": "2026-05-23T16:01:10"
      }
    ]
  }
  ```

#### PUT `/sessions/{session_id}/title`
* **Request (JSON)**:
  ```json
  {
    "title": "更新后的会话标题"
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "message": "Session title updated successfully",
    "session_id": 1,
    "title": "更新后的会话标题"
  }
  ```

#### DELETE `/sessions/{session_id}`
* **Response (200 OK)**:
  *(Note: Cascade deletes Persona/Messages, clears corresponding memories in ChromaDB, and relinks children sessions to its grandparent to maintain the timeline)*
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

#### DELETE `/sessions/messages/{message_id}`
* **Response (200 OK)**:
  ```json
  {
    "message": "Message deleted successfully",
    "message_id": 1
  }
  ```

---

### 4. Conversations (`/chat`)

#### POST `/chat`
* **Request (JSON)**:
  ```json
  {
    "session_id": 1,
    "user_message": "把它改成打印 'Hello World' 呢？",
    "use_reasoning": null
  }
  ```
  | Field | Type | Required | Description |
  | :--- | :--- | :--- | :--- |
  | `session_id` | `int` | ✅ | Target session ID |
  | `user_message` | `string` | ✅ | The user's input message |
  | `use_reasoning` | `bool \| null` | ❌ | Model override: `true` = force reasoning model (`chat_model`), `false` = force non-reasoning model (`non_reasoning_chat_model`), `null` (default) = follow `config.yaml → reasoning_mode` |

* **Response (200 OK)**:
  ```json
  {
    "reply": "好的，这是改写后的代码：print('Hello World') (≧▽≦)",
    "emotion_tag": "开心",
    "affection_change": 1,
    "affection_score": 11,
    "model_used": "ep-m-20260313153437-67wfk"
  }
  ```
  | Field | Type | Description |
  | :--- | :--- | :--- |
  | `reply` | `string` | Character's reply text |
  | `emotion_tag` | `string` | Character's current emotion label (Chinese) |
  | `affection_change` | `int` | Affection delta from this message (-5 ~ 5) |
  | `affection_score` | `int` | Updated total affection score |
  | `model_used` | `string` | The actual model name used for this reply (useful for UI display or debugging) |
