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

## PUT `/utils/settings`
* `translation_model` accepts a nonblank model ID (up to 200 characters), independently of chat, memory and TTS settings.
* Accepts the additional GET fields above except read-only `model_catalog`. Auxiliary thinking modes are `enabled`/`disabled`; effort is a supported string. `reasoning_effort: null` resets the global effort to the provider default. Model IDs must be nonblank and profile IDs unique.
* `reasoning_mode` controls thinking independently of `default_chat_model`. Invalid model/thinking/effort combinations return `400` before persistence; malformed fields return `422`.
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
