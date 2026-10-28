# HTTP API 总表

本页是前后端共享的 HTTP 接口索引。请求、响应、错误与兼容规则按领域维护，业务边界需结合实现和回归测试确认。

| 任务 | 详细契约 |
| --- | --- |
| 连接、鉴权、配置与语音 | [通用接口](docs/api/GENERAL.md) |
| 角色卡、翻译、CHARX 与立绘 | [角色接口](docs/api/CHARACTERS.md) |
| 故事分支、消息、状态与长期记忆 | [会话接口](docs/api/SESSIONS.md)、[记忆规则补充](docs/api/MEMORY_API.md) |
| 独立世界书、词条与绑定 | [世界书接口](docs/api/LOREBOOKS.md) |
| 模型对话、SSE 与候选切换 | [聊天接口](docs/api/CHAT.md) |
| 修改接口或排查文档漂移 | [维护与校验说明](docs/api/README.md) |

应用提供 `/docs` 和 `/openapi.json`，可查看框架声明的路径、参数和请求结构；它们不完整描述动态响应、SSE 与业务规则。本文配置路径相对 `app-backend/`；资源 ID、版本号和配置值需按实际数据替换。

## 通用约定

* **Base URL**: `http://127.0.0.1:8000`
* **Content-Type**: `application/json` (except file uploads)
* **Authentication**: Business API endpoints require the `X-API-Key` header when `ACCESS_API_KEY` is configured in `.env`. Public avatar files under `/assets/avatars/` are exempt; the built-in `/docs`, `/redoc`, and `/openapi.json` pages are also currently public.
  - Header: `X-API-Key: <your-secret>`
  - If `ACCESS_API_KEY` is empty (local dev), the header can be omitted.
  - Missing or wrong key returns `403 Forbidden`.
* **CORS**: Enabled for `GET`, `POST`, `PUT`, `DELETE`, `OPTIONS` methods and all headers.
* **Static Assets & Audio**: 
  - Uploaded avatars: `http://127.0.0.1:8000/assets/avatars/{filename}`
  - Synthesized speech: `http://127.0.0.1:8000/audio/{filename}` (requires the authentication header; see [audio recovery limitations](docs/api/GENERAL.md#get-audiofilename))
  - Static asset URLs must be public or short-lived signed URLs. Clients must never put the long-lived API key in URL query parameters.

---

## 接口索引

### 通用、配置与音频 API

[请求与响应详情](docs/api/GENERAL.md)
| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **GET** | `/` | Service health status check |
| **POST** | `/upload/avatar` | Upload raw avatar image |
| **GET** | `/utils/settings` | Retrieve active customizable dialogue and retrieval settings |
| **PUT** | `/utils/settings` | Update customizable dialogue and retrieval settings (instant & persistent) |
| **POST** | `/utils/tts` | Synthesize speech from text (returns audio URL) |
| **GET** | `/audio/{filename}` | Download/play synthesized audio file; missing files may require a new TTS request |

### 角色、导入与立绘 API

[请求与响应详情](docs/api/CHARACTERS.md)
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

### 会话、消息与记忆 API

[请求与响应详情](docs/api/SESSIONS.md)
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
| **GET** | `/sessions/{session_id}/memory-consolidations` | List consolidation previews and review state |
| **POST** | `/sessions/{session_id}/memory-consolidations/preview` | Preview consolidation suggestions |
| **POST** | `/sessions/{session_id}/memory-consolidations/{batch_id}/apply` | Apply selected groups with revision checking |
| **PUT** | `/sessions/{session_id}/memory-consolidations/{batch_id}/groups/{group_id}` | Review or edit one suggestion group |
| **POST** | `/sessions/{session_id}/memory-consolidations/{batch_id}/undo` | Undo an applied batch within the visible story boundary |
| **GET** | `/sessions/{session_id}/compile_prompt` | Preview the assembled prompt and its heuristic Token range/section breakdown |

### 世界书 API

[请求与响应详情](docs/api/LOREBOOKS.md)
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

### 聊天与 SSE API

[请求与响应详情](docs/api/CHAT.md)

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| **POST** | `/chat` | Submit message, run RAG, compile prompt, write response (blocking) |
| **POST** | `/chat/stream` | Stream reply chunk-by-chunk using Server-Sent Events (SSE) |
| **POST** | `/chat/switch_candidate` | Switch active assistant message candidate version (recalculating affection/mood) |
