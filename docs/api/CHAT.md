# 聊天与 SSE API

[API 总表](../../API_TABLE.md) · [接口维护与校验](README.md)

快速定位：[普通回复](#post-chat) · [SSE](#post-chatstream) · [候选切换](#post-chatswitch_candidate)

Both `/chat` and `/chat/stream` accept independent model settings, including regeneration. Supplying `model` or `thinking_mode` takes precedence over legacy `use_reasoning`. Invalid combinations fail with `400` before writing a user message. Story overrides are client-local; global defaults persist on the server. See [model settings](../../docs/features/MODEL_SELECTION.md).

## POST `/chat`

`model` 可选，省略时使用全局默认；`thinking_mode` 可取 `inherit`、`enabled`、`disabled`，`reasoning_effort` 省略时沿用全局强度。`use_reasoning` 为旧客户端保留，会选择原有思考或非思考模型槽位。`is_regenerate: true` 重新生成当前轮回复，`user_nickname` 注入 Prompt，采样参数均可单独覆盖。

* **Request (JSON)**:
<!-- request-example: POST /chat; POST /chat/stream -->
  ```json
  {
    "session_id": 1,
    "user_message": "你好呀，爱丽丝",
    "model": "deepseek-flash",
    "thinking_mode": "enabled",
    "reasoning_effort": "max",
    "use_reasoning": null,
    "is_regenerate": false,
    "user_nickname": "用户",
    "temperature": null,
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

## POST `/chat/stream`
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

## POST `/chat/switch_candidate`

`message_id` 指向需要激活的 assistant 候选消息。


Only candidates belonging to the latest active user message can be switched.
Sending the next user message confirms and freezes the previous turn; changing an
earlier confirmed turn requires creating a session branch.

* **Request (JSON)**:
<!-- request-example: POST /chat/switch_candidate -->
  ```json
  {
    "message_id": 6
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
