from pydantic import BaseModel

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
    parent_session_id: int | None = None
    title: str = "New Story"

class SessionTitleUpdate(BaseModel):
    title: str

class ChatRequest(BaseModel):
    session_id: int
    user_message: str
    # 可选：覆盖 config.yaml 中的 reasoning_mode 设置
    # True  → 强制使用思考模型（chat_model）
    # False → 强制使用非思考模型（non_reasoning_chat_model）
    # None  → 沿用 config.yaml 的默认配置（reasoning_mode 字段）
    use_reasoning: bool | None = None


class MessageUpdate(BaseModel):
    content: str


class SettingsUpdate(BaseModel):
    temperature: float | None = None
    reasoning_mode: bool | None = None
    context_history_limit: int | None = None
    retrieval_top_k: int | None = None
    retrieval_min_importance: float | None = None
    retrieval_max_distance: float | None = None
    lorebook_scan_depth: int | None = None
    lorebook_token_budget: int | None = None
    lorebook_max_recursive_passes: int | None = None
    cognition_max_words: int | None = None
    retrieval_half_life_turns: int | None = None
    retrieval_candidate_multiplier: int | None = None
    max_tokens: int | None = None
