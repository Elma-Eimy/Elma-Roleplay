from pydantic import BaseModel, Field, field_validator
from typing import Optional, Literal

class CharacterCreate(BaseModel):
    name: str
    avatar_path: str = ""
    description: str = ""
    personality: str = ""
    scenario: str = ""
    first_mes: str = ""
    mes_example: str = ""
    creator_notes: str = ""
    system_prompt_override: str = ""
    post_history_instructions: str = ""
    tags: list[str] = []
    extensions: dict = {}

class SessionCreate(BaseModel):
    character_id: int
    parent_session_id: Optional[int] = None
    title: str = "New Story"
    greeting_index: Optional[int] = None
    start_message_id: Optional[int] = None


class CharacterTranslationRequest(BaseModel):
    card: CharacterCreate
    force: bool = False

class SessionTitleUpdate(BaseModel):
    title: str

class ChatRequest(BaseModel):
    session_id: int
    user_message: str
    model: Optional[str] = Field(None, min_length=1, max_length=200)
    thinking_mode: Optional[Literal["inherit", "enabled", "disabled"]] = None
    # 旧客户端仍可用该字段同时选择旧模型槽位与思考模式。
    use_reasoning: Optional[bool] = None
    is_regenerate: bool = False
    user_nickname: Optional[str] = "用户"
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    repetition_penalty: Optional[float] = None
    reasoning_effort: Optional[str] = None

    @field_validator("model")
    @classmethod
    def valid_model(cls, value):
        if value is not None and not value.strip():
            raise ValueError("模型 ID 不能为空")
        return value.strip() if value is not None else None


class MessageUpdate(BaseModel):
    content: str


class ModelProfile(BaseModel):
    id: str = Field(min_length=1, max_length=200)
    label: str = Field(default="", max_length=200)
    adapter: Literal["compatible", "deepseek", "reasoning"] = "compatible"

    @field_validator("id")
    @classmethod
    def nonblank_id(cls, value):
        if not value.strip():
            raise ValueError("模型 ID 不能为空")
        return value.strip()


class SettingsUpdate(BaseModel):
    translation_model: Optional[str] = Field(None, min_length=1, max_length=200)
    default_chat_model: Optional[str] = Field(None, min_length=1, max_length=200)
    model_profiles: Optional[list[ModelProfile]] = Field(None, max_length=100)
    memory_model: Optional[str] = Field(None, min_length=1, max_length=200)
    memory_thinking_mode: Optional[Literal["enabled", "disabled"]] = None
    memory_reasoning_effort: Optional[str] = None
    tts_preprocess_model: Optional[str] = Field(None, min_length=1, max_length=200)
    tts_thinking_mode: Optional[Literal["enabled", "disabled"]] = None
    tts_reasoning_effort: Optional[str] = None

    @field_validator("default_chat_model", "memory_model", "tts_preprocess_model", "translation_model")
    @classmethod
    def valid_model_id(cls, value):
        if value is not None and not value.strip():
            raise ValueError("模型 ID 不能为空")
        return value.strip() if value is not None else None

    @field_validator("model_profiles")
    @classmethod
    def unique_profiles(cls, profiles):
        if profiles is not None and len({profile.id for profile in profiles}) != len(profiles):
            raise ValueError("模型 ID 不能重复")
        return profiles

    temperature: Optional[float] = None
    reasoning_mode: Optional[bool] = None
    context_history_limit: Optional[int] = None
    memory_handoff_margin: Optional[int] = None
    retrieval_top_k: Optional[int] = None
    retrieval_context_turns: Optional[int] = None
    retrieval_query_max_chars: Optional[int] = None
    retrieval_min_importance: Optional[float] = None
    retrieval_max_distance: Optional[float] = None
    lorebook_scan_depth: Optional[int] = None
    lorebook_token_budget: Optional[int] = None
    lorebook_max_recursive_passes: Optional[int] = None
    cognition_max_words: Optional[int] = None
    retrieval_half_life_turns: Optional[int] = None
    retrieval_candidate_multiplier: Optional[int] = None
    max_tokens: Optional[int] = None
    top_p: Optional[float] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    repetition_penalty: Optional[float] = None
    reasoning_effort: Optional[str] = None

class SwitchCandidateRequest(BaseModel):
    message_id: int


class TTSRequest(BaseModel):
    message_id: Optional[int] = None
    text: str
    voice: Optional[str] = None
    speed: Optional[float] = 1.0


# ──────────────────────────────────────────────
# 世界书 (Lorebook) 相关 Schema 定义
# ──────────────────────────────────────────────

class LorebookEntry(BaseModel):
    keys: list[str] = []
    content: str
    enabled: bool = True
    constant: bool = False
    case_sensitive: bool = False
    selective: bool = False
    selective_logic: str = "and_any"
    secondary_keys: list[str] = []
    use_regex: bool = False
    probability: int = 100
    use_probability: bool = True
    position: str = "before_char"
    insertion_order: int = 100
    # SillyTavern 的 @ Depth 条目使用这两个可选元数据；其它位置会忽略它们。
    depth: int = 4
    role: str = "system"
    # Outlet 当前只保真存储，不会自动注入；后续可配合宏系统使用。
    outlet: str = ""

class LorebookCreate(BaseModel):
    name: str
    description: Optional[str] = ""
    scan_depth: Optional[int] = None
    token_budget: Optional[int] = None
    recursive_scanning: Optional[bool] = None
    entries: list[LorebookEntry] = []

class LorebookUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    scan_depth: Optional[int] = None
    token_budget: Optional[int] = None
    recursive_scanning: Optional[bool] = None
    entries: Optional[list[LorebookEntry]] = None


# ──────────────────────────────────────────────
# RAG 记忆相关 Schema 定义
# ──────────────────────────────────────────────

class MemoryCreateRequest(BaseModel):
    content: str
    importance_score: Optional[float] = 0.8
    memory_type: Optional[str] = "fact"

class MemoryUpdateRequest(BaseModel):
    content: str
    importance_score: float


class MemoryConsolidationPreviewRequest(BaseModel):
    after_id: int = Field(0, ge=0)


class MemoryConsolidationApplyRequest(BaseModel):
    group_ids: list[int] = Field(min_length=1, max_length=12)

    @field_validator("group_ids")
    @classmethod
    def valid_groups(cls, value):
        if any(i < 0 for i in value) or len(set(value)) != len(value):
            raise ValueError("整理分组编号必须非负且不重复")
        return value


