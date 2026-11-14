# 通用、配置与音频 API

[API 总表](../../API_TABLE.md) · [接口维护与校验](README.md)

快速定位：[服务检查](#get-) · [配置](#get-utilssettings) · [语音](#post-utilstts) · [音频下载](#get-audiofilename)

## GET `/`
* **Response (200 OK)**:
  ```json
  {
    "status": "Core Engine is running"
  }
  ```

## POST `/upload/avatar`
* **Request**: `multipart/form-data`
  - `file`: Binary image file (PNG/JPG/JPEG/WEBP). Size is limited by `app.max_card_size_mb` in `config.yaml` (schema default: 10 MB); larger uploads return `413`.
* **Response (200 OK)**:
  ```json
  {
    "message": "Avatar uploaded successfully",
    "avatar_path": "assets/avatars/4a6b2c8d_helper.png"
  }
  ```

## GET `/utils/settings`
* Also returns `translation_model`, `translation_thinking_mode` and `translation_reasoning_effort`, independently selectable for character reading translations. Existing translations remain unchanged; use `force: true` to refresh them. Missing task models initialize once during configuration migration, retaining the previous effective model.
* Also returns `default_chat_model`, `chat_thinking_mode`, `model_profiles` (editable `{id,label,adapter,thinking?,efforts?}` entries), `model_catalog` (read-only capabilities), `memory_model`, `memory_thinking_mode`, `memory_reasoning_effort`, `tts_preprocess_model`, `tts_thinking_mode`, and `tts_reasoning_effort`. Null or omitted profile capability fields use adapter defaults; explicit effort lists override them. Supported effort names: `minimal`, `low`, `medium`, `high`, `xhigh`, `max`; duplicates are rejected.
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

## PUT `/utils/settings`
* `translation_model` accepts a nonblank model ID (up to 200 characters), independently of chat, memory and TTS settings.
* Accepts the additional GET fields above except read-only `model_catalog`. Auxiliary thinking modes are `enabled`/`disabled`; effort is a supported string. `reasoning_effort: null` resets the global effort to the provider default. Model IDs must be nonblank and profile IDs unique.
* `chat_thinking_mode` controls thinking independently of `default_chat_model`; `reasoning_mode` remains a boolean compatibility alias. Conflicting aliases return `400`. All task modes use `enabled`/`disabled`; nullable task efforts do not inherit chat effort. Fixed-thinking models cannot be explicitly disabled. Invalid model combinations return `400`, malformed fields return `422`.
* Updates are serialized, fully validated and atomically saved before runtime publication. Save failures return `500` and retain the old file and runtime state. The new frontend omits `reasoning_mode` when sending `chat_thinking_mode`.
* Implicit defaults for fixed-thinking models are normalized to `enabled`, so a complete GET response can be saved unchanged. Explicitly disabling such a model still returns `400`. An empty model capability `efforts` list suppresses the effort parameter, including inherited or explicitly supplied effort values.
* **Supported fields**: Only fields declared by `app-backend/schemas.py::SettingsUpdate` are accepted. Retrieval scoring weights, ancestor weight, deduplication threshold, and graph thresholds are not exposed by this HTTP API; edit YAML and restart for those settings. `memory_handoff_margin` is accepted by PUT but is not currently included in the GET response.
* **Request (JSON)**: *(All fields optional)*
<!-- request-example: PUT /utils/settings -->
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

## POST `/utils/tts`

`message_id` 可选，用于关联数据库消息；`voice` 可选，用于指定音色；`speed` 可选，默认 `1.0`。

* **Request (JSON)**:
<!-- request-example: POST /utils/tts -->
  ```json
  {
    "message_id": 12,
    "text": "你好呀，很高兴认识你！",
    "voice": "冰糖",
    "speed": 1.0
  }
  ```
* **Response (200 OK)**:
  ```json
  {
    "audio_url": "/audio/msg_12_p2_冰糖_1.00.mp3"
  }
  ```

## GET `/audio/{filename}`
* **Response (200 OK)**: Binary audio stream (typically MP3/WAV format).
  - *Current limitation*: The download route only recognizes legacy `msg_{id}_{voice}_{speed}.mp3` names for recovery, while the TTS service now generates `msg_{id}_p2_{voice}_{speed}.mp3`. Missing versioned files therefore return `404` on direct download. Request `POST /utils/tts` with the original `message_id` and matching voice/speed to regenerate the file and use the returned URL. Plain-text hash files cannot be regenerated from the download URL alone.

---
