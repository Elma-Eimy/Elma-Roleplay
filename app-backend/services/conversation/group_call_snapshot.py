"""在轮次起始冻结模型选择、成员采样参数和历史预算。"""
import copy
import json
import hashlib
import math
from urllib.parse import urlsplit, urlunsplit
from dataclasses import dataclass, field
from types import SimpleNamespace

from sqlalchemy import text

from core.config import settings
from core.models import SessionPersona
from services.conversation import group_history_service as history
from services.conversation.session_access import group_session_operation
from services.infrastructure.model_capabilities import resolve_selection, generation_controls, model_capability
from services.infrastructure.llm_provider import GroupModelConnection


@dataclass(frozen=True)
class GroupCallSnapshot:
    director_json: str
    members: tuple[tuple[int, str], ...]
    history_limit: int
    call_timeout: float
    connection: GroupModelConnection = field(repr=False)
    turn_policy: int = 0
    inherited_recall: bool = False
    output_attempts: int = 1
    fact_recall: bool = False
    experience_guard: bool = False
    review_reasoning_effort: str | None = None
    shared_chat: bool = False
    reply_target: bool = False

    def member_parameters(self, persona_id):
        for pid, parameters in self.members:
            if pid == persona_id:
                return parameters
        raise ValueError("发言成员不属于调用快照")


def require_executable_calls(snapshot):
    """旧策略字段只用于读取快照，不能恢复已移除的执行链路。"""
    if (not snapshot.shared_chat or snapshot.turn_policy or snapshot.experience_guard
            or snapshot.review_reasoning_effort is not None or snapshot.output_attempts != 1
            or any('response_format' in json.loads(encoded) for _, encoded in snapshot.members)):
        from services.conversation.session_access import SessionKindConflict
        raise SessionKindConflict('旧群聊生成、转换和审查链路已移除，请重新生成共同群聊候选')


def persist_group_calls(snapshot, max_steps, member_ids):
    """逐字段保存可重放参数；连接地址只保存无凭据摘要。"""
    error = history.GroupSessionValidationError
    if not isinstance(snapshot, GroupCallSnapshot):
        raise error("新任务需要冻结调用参数")
    if type(snapshot.turn_policy) is not int or snapshot.turn_policy not in (0, 1, 2):
        raise error("回合策略无效")
    if type(max_steps) is not int or not 1 <= max_steps <= 6:
        raise error("成功步数需要在 1–6 之间")
    if type(snapshot.history_limit) is not int or not 1 <= snapshot.history_limit <= 500:
        raise error("历史窗口无效")
    if type(snapshot.call_timeout) not in (float, int) or not math.isfinite(snapshot.call_timeout) or snapshot.call_timeout <= 0:
        raise error("调用超时无效")

    def parameters(encoded):
        try:
            value = json.loads(encoded)
        except (ValueError, TypeError):
            raise error("调用参数无效") from None
        allowed = {"model", "max_tokens", "temperature", "top_p", "presence_penalty", "frequency_penalty",
                   "reasoning_effort", "extra_body", "response_format"}
        if not isinstance(value, dict) or not set(value) <= allowed:
            raise error("调用参数含非白名单字段")
        if not isinstance(value.get("model"), str) or not value["model"].strip():
            raise error("模型名无效")
        if type(value.get("max_tokens")) is not int or value["max_tokens"] <= 0:
            raise error("输出预算无效")
        for key in ("temperature", "top_p", "presence_penalty", "frequency_penalty"):
            if key in value and (type(value[key]) not in (int, float) or not math.isfinite(value[key])):
                raise error("采样参数无效")
        if "reasoning_effort" in value and value["reasoning_effort"] not in ("none", "minimal", "low", "medium", "high", "xhigh", "max"):
            raise error("思考参数无效")
        if "response_format" in value and value["response_format"] != {"type": "json_object"}:
            raise error("群聊只支持 JSON object 格式约束")
        extra = value.get("extra_body", {})
        if not isinstance(extra, dict) or not set(extra) <= {"thinking", "repetition_penalty"}:
            raise error("扩展参数含非白名单字段")
        if "thinking" in extra and extra["thinking"] not in ({"type": "enabled"}, {"type": "disabled"}):
            raise error("思考开关无效")
        if "repetition_penalty" in extra and (type(extra["repetition_penalty"]) not in (int, float)
                or not math.isfinite(extra["repetition_penalty"])):
            raise error("重复惩罚无效")
        return value

    ids = [pid for pid, _ in snapshot.members]
    if any(type(pid) is not int for pid in ids) or len(ids) != len(set(ids)) or set(ids) != member_ids:
        raise error("调用快照成员不属于本群")
    try:
        address = urlsplit(snapshot.connection.base_url)
        if address.scheme.lower() not in ("http", "https") or not address.hostname or address.username or address.password or address.query or address.fragment:
            raise ValueError
        normalized = urlunsplit((address.scheme.lower(), address.netloc.lower(), address.path.rstrip("/"), "", ""))
    except (ValueError, AttributeError, TypeError):
        raise error("提供方地址必须是不含凭据的 HTTP 地址") from None
    value = dict(policy_version=2, max_steps=max_steps, history_limit=snapshot.history_limit,
                 call_timeout=snapshot.call_timeout, director=parameters(snapshot.director_json),
                 members=[dict(persona_id=pid, parameters=parameters(encoded)) for pid, encoded in snapshot.members])
    if type(snapshot.shared_chat) is not bool:
        raise error("共同群聊策略无效")
    if snapshot.shared_chat:
        if snapshot.turn_policy or snapshot.experience_guard or any(
                'response_format' in json.loads(encoded) for _, encoded in snapshot.members):
            raise error('共同群聊不能启用角色 JSON 或裁决审查')
        value["shared_chat"] = True
    if type(snapshot.reply_target) is not bool or snapshot.reply_target and not snapshot.shared_chat:
        raise error('明确回应对象只能用于共同群聊')
    if snapshot.reply_target:
        value['reply_target'] = True
    if type(snapshot.inherited_recall) is not bool:
        raise error("继承记忆策略无效")
    if snapshot.inherited_recall:
        value["inherited_recall"] = True
    if snapshot.turn_policy:
        value["turn_policy"] = snapshot.turn_policy
    if type(snapshot.output_attempts) is not int or snapshot.output_attempts not in (1, 3):
        raise error("输出重试策略无效")
    if snapshot.output_attempts != 1:
        value["output_attempts"] = snapshot.output_attempts
    if type(snapshot.fact_recall) is not bool:
        raise error("事实召回策略无效")
    if snapshot.fact_recall:
        value["fact_recall"] = True
    if type(snapshot.experience_guard) is not bool:
        raise error("亲历审查策略无效")
    if snapshot.experience_guard:
        value["experience_guard"] = True
    if snapshot.review_reasoning_effort not in (None, 'low'):
        raise error('审查思考参数无效')
    if snapshot.review_reasoning_effort is not None:
        value['review_reasoning_effort'] = snapshot.review_reasoning_effort
    return json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False), hashlib.sha256(normalized.encode()).hexdigest()


def validate_group_call_selection(encoded, *, model, thinking_mode, reasoning_effort):
    """首次接受前核对请求与所有调用参数；继承值取冻结结果。"""
    value = json.loads(encoded)
    director = value["director"]
    capability = model_capability(director["model"])
    thinking = director.get("extra_body", {}).get("thinking", {}).get("type")
    frozen_thinking = thinking == "enabled" if thinking is not None else capability["thinking"] == "always"
    config = SimpleNamespace(LLM_DEFAULT_CHAT_MODEL=director["model"],
        LLM_MODEL_PROFILES=copy.deepcopy(settings.LLM_MODEL_PROFILES),
        LLM_REASONING_MODE=frozen_thinking, LLM_REASONING_EFFORT=director.get("reasoning_effort"))
    try:
        selection = resolve_selection(model, thinking_mode, effort=reasoning_effort, config=config)
    except ValueError as exc:
        raise history.GroupSessionValidationError(str(exc)) from None
    controls = generation_controls(selection, config=config)
    for parameters in (director, *(member["parameters"] for member in value["members"])):
        if (parameters["model"] != selection.model
                or parameters.get("reasoning_effort") != controls.get("reasoning_effort")
                or parameters.get("extra_body", {}).get("thinking") != controls.get("extra_body", {}).get("thinking")):
            raise history.GroupSessionValidationError("请求的模型选择与冻结调用参数不一致")


def restore_group_calls(candidate, member_ids):
    """续接只恢复已保存参数，提供方可轮换凭据但不能切服。"""
    try:
        value = json.loads(candidate.call_snapshot_json)
        limit = value.get("group_card_limit", 0)
        if type(limit) is not int or limit < 0:
            raise ValueError
        if (candidate.protocol_version != 2 or set(value) - {"reply_target", "shared_chat", "turn_policy", "inherited_recall", "group_card_limit", "output_attempts", "fact_recall", "experience_guard", "review_reasoning_effort"} != {
                "policy_version", "max_steps", "history_limit", "call_timeout", "director", "members"}
                or value["policy_version"] != 2):
            raise ValueError
        if any(set(member) != {"persona_id", "parameters"} for member in value["members"]):
            raise ValueError
        snapshot = GroupCallSnapshot(json.dumps(value["director"]),
            tuple((member["persona_id"], json.dumps(member["parameters"])) for member in value["members"]),
            value["history_limit"], value["call_timeout"], GroupModelConnection(settings.CHAT_BASE_URL, settings.CHAT_API_KEY),
            value.get("turn_policy", 0), value.get("inherited_recall", False), value.get("output_attempts", 1), value.get("fact_recall", False), value.get("experience_guard", False), value.get('review_reasoning_effort'), value.get('shared_chat', False), value.get('reply_target', False))
        _, fingerprint = persist_group_calls(snapshot, value["max_steps"], member_ids)
        def selection(parameters):
            return (parameters["model"], parameters.get("reasoning_effort"),
                    parameters.get("extra_body", {}).get("thinking"))
        if any(selection(member["parameters"]) != selection(value["director"]) for member in value["members"]):
            raise ValueError
        if fingerprint != candidate.provider_fingerprint:
            raise ValueError
        return snapshot, value["max_steps"]
    except (ValueError, TypeError, KeyError, AttributeError):
        raise history.GroupSessionValidationError("原调用参数缺失、损坏或提供方已变化，请整轮重生成") from None


@group_session_operation
def capture_group_calls(session_id, db, *, model=None, thinking_mode=None, reasoning_effort=None, shared_chat=True):
    if shared_chat is not True:
        raise history.GroupSessionValidationError('旧群聊生成链路已移除')
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
        output_limit = config.LLM_MAX_TOKENS
        return json.dumps({"model": selection.model, "max_tokens": output_limit, **controls,
            **({"response_format": {"type": "json_object"}} if character is None and settings.LLM_GROUP_JSON_MODE else {})}, ensure_ascii=False)
    db.rollback()
    db.expire_all()
    db.execute(text("BEGIN"))
    try:
        history._require_group(session_id, db)
        members = tuple((member.id, parameters(member.character)) for member in db.query(SessionPersona)
                        .filter_by(session_id=session_id).order_by(SessionPersona.member_slot).all())
        return GroupCallSnapshot(parameters(), members, min(500, max(1, config.APP_CONTEXT_HISTORY_LIMIT)), float(config.LLM_TIMEOUT),
                                 connection, inherited_recall=True, fact_recall=True, shared_chat=True, reply_target=True)
    finally:
        db.rollback()
