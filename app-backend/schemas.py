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
