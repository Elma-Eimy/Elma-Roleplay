"""在轮次起始冻结模型选择、成员采样参数和历史预算。"""
import copy
import json
from dataclasses import dataclass, field
from types import SimpleNamespace

from sqlalchemy import text

from core.config import settings
from core.models import SessionPersona
from services.conversation import group_history_service as history
from services.conversation.session_access import group_session_operation
from services.infrastructure.model_capabilities import resolve_selection, generation_controls
from services.infrastructure.llm_provider import GroupModelConnection


@dataclass(frozen=True)
class GroupCallSnapshot:
    director_json: str
    members: tuple[tuple[int, str], ...]
    history_limit: int
    call_timeout: float
    connection: GroupModelConnection = field(repr=False)

    def member_parameters(self, persona_id):
        for pid, parameters in self.members:
            if pid == persona_id:
                return parameters
        raise ValueError("发言成员不属于调用快照")


@group_session_operation
def capture_group_calls(session_id, db, *, model=None, thinking_mode=None, reasoning_effort=None):
    history._require_group(session_id, db)
    history._require_clean_transaction(db)
    # 只复制模型参数，不复制或序列化连接凭据。
    names = ("LLM_DEFAULT_CHAT_MODEL", "CHAT_MODEL_REASONING", "CHAT_MODEL_NON_REASONING", "LLM_MODEL_PROFILES",
             "LLM_REASONING_MODE", "LLM_REASONING_EFFORT", "LLM_TEMPERATURE", "LLM_TOP_P", "LLM_PRESENCE_PENALTY",
             "LLM_FREQUENCY_PENALTY", "LLM_REPETITION_PENALTY", "LLM_MAX_TOKENS", "LLM_TIMEOUT", "APP_CONTEXT_HISTORY_LIMIT")
    state = vars(settings).copy()
    config = SimpleNamespace(**{name: copy.deepcopy(state[name]) for name in names})
    connection = GroupModelConnection(state["CHAT_BASE_URL"], state["CHAT_API_KEY"])
    selection = resolve_selection(model, thinking_mode, effort=reasoning_effort, config=config)
    def parameters(character=None):
        ext = character.extensions if character is not None else None
        try:
            ext = json.loads(ext) if isinstance(ext, str) else ext
        except (ValueError, TypeError):
            ext = None
        ext = ext if isinstance(ext, dict) else {}
        controls = generation_controls(selection, temperature=ext.get("temperature", config.LLM_TEMPERATURE),
            top_p=ext.get("top_p", config.LLM_TOP_P), presence_penalty=ext.get("presence_penalty", config.LLM_PRESENCE_PENALTY),
            frequency_penalty=ext.get("frequency_penalty", config.LLM_FREQUENCY_PENALTY),
            repetition_penalty=ext.get("repetition_penalty", config.LLM_REPETITION_PENALTY), config=config)
        return json.dumps({"model": selection.model, "max_tokens": config.LLM_MAX_TOKENS, **controls}, ensure_ascii=False)
    db.rollback()
    db.expire_all()
    db.execute(text("BEGIN"))
    try:
        history._require_group(session_id, db)
        members = tuple((member.id, parameters(member.character)) for member in db.query(SessionPersona)
                        .filter_by(session_id=session_id).order_by(SessionPersona.member_slot).all())
        return GroupCallSnapshot(parameters(), members, min(500, max(1, config.APP_CONTEXT_HISTORY_LIMIT)), float(config.LLM_TIMEOUT),
                                 connection)
    finally:
        db.rollback()
