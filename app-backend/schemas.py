from pydantic import BaseModel
from typing import Optional

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

class SessionTitleUpdate(BaseModel):
    title: str

class ChatRequest(BaseModel):
    session_id: int
    user_message: str
    # 可选：覆盖 config.yaml 中的 reasoning_mode 设置
    # True  → 强制使用思考模型（chat_model）
    # False → 强制使用非思考模型（non_reasoning_chat_model）
    # None  → 沿用 config.yaml 的默认配置（reasoning_mode 字段）
    use_reasoning: Optional[bool] = None
    is_regenerate: bool = False
    user_nickname: Optional[str] = "用户"
    temperature: Optional[float] = None
    top_p: Optional[float] = None
    presence_penalty: Optional[float] = None
    frequency_penalty: Optional[float] = None
    repetition_penalty: Optional[float] = None
    reasoning_effort: Optional[str] = None


class MessageUpdate(BaseModel):
    content: str


class SettingsUpdate(BaseModel):
    temperature: Optional[float] = None
    reasoning_mode: Optional[bool] = None
    context_history_limit: Optional[int] = None
    retrieval_top_k: Optional[int] = None
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
    secondary_keys: list[str] = []
    position: str = "before_char"
    insertion_order: int = 100

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


