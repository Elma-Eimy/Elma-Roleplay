"""单聊资源加载入口；内部步骤复用已加载对象，不重复做类型判断。"""
from core.models import Session, SessionPersona, ChatMessage
from sqlalchemy.orm import Session as DBSession


class SessionKindConflict(Exception):
    """当前操作不支持目标故事的类型。"""


RESOURCE_ARGUMENTS = {
    "session_id": "session", "parent_session_id": "session",
    "persona_id": "persona", "message_id": "message",
}


def session_kind_agnostic(reason):
    """声明按明确资源归属运行的共享算法，供入口覆盖检查区分业务限制。"""
    if not isinstance(reason, str) or not reason.strip():
        raise ValueError("共享操作必须说明不限制会话类型的原因")

    def declare(function):
        function.__session_kind_agnostic__ = reason
        return function
    return declare


def check_single_chat_arguments(arguments, db):
    """HTTP 边界统一解析资源 ID；缺少数据库依赖时拒绝继续执行。"""
    loaders = {"session": get_single_session, "persona": get_single_persona,
               "message": get_single_message}
    for name, resource in RESOURCE_ARGUMENTS.items():
        value = arguments.get(name)
        if value is not None:
            if db is None:
                raise RuntimeError(f"单聊入口包含 {name}，但未声明 db 依赖")
            loaders[resource](value, db)


def _single(session: Session | None) -> Session | None:
    if session is not None and session.kind != "single":
        raise SessionKindConflict("此操作仅支持单聊，请使用群聊入口")
    return session


def get_single_session(session_id: int, db: DBSession) -> Session | None:
    return _single(db.get(Session, session_id))


def get_single_persona(persona_id: int, db: DBSession) -> SessionPersona | None:
    persona = db.get(SessionPersona, persona_id)
    if persona is not None:
        _single(persona.session)
    return persona


def get_single_message(message_id: int, db: DBSession) -> ChatMessage | None:
    message = db.get(ChatMessage, message_id)
    if message is not None:
        _single(message.session)
    return message
