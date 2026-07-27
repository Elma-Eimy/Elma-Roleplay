"""查询 Persona 继承链以及一条分支上可见的会话区段。"""

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from core.models import ChatMessage, Session, SessionPersona


def get_ancestor_persona_ids(persona_id: int, db: DBSession) -> list[int]:
    """返回当前 Persona 到根 Persona 的 ID 链，顺序为当前到最早祖先。"""
    sql = """
    WITH RECURSIVE ancestor(id, parent_id) AS (
        SELECT id, parent_persona_id FROM session_personas WHERE id = :persona_id
        UNION ALL
        SELECT sp.id, sp.parent_persona_id
        FROM session_personas sp
        JOIN ancestor a ON sp.id = a.parent_id
    )
    SELECT id FROM ancestor;
    """
    try:
        result = db.execute(text(sql), {"persona_id": persona_id}).fetchall()
        ids = [row[0] for row in result]
        if ids:
            return ids
    except Exception as exc:
        print(
            "[WARN] get_ancestor_persona_ids: SQL CTE 递归查询失败: "
            f"{exc}. 已自动回退到循环同步遍历。"
        )

    ids = []
    current_id = persona_id
    visited = set()
    while current_id is not None and current_id not in visited:
        visited.add(current_id)
        ids.append(current_id)
        persona = db.get(SessionPersona, current_id)
        if persona is None:
            break
        current_id = persona.parent_persona_id

    return ids


def build_branch_turn_segments(persona_id: int, db: DBSession) -> list[dict]:
    """返回当前到根会话在本分支上可见的消息区段。

    ``through_message_id`` 是祖先会话中可见的分叉边界；
    ``copied_boundary_message_id`` 标识复制到子会话的边界消息，供轮次计算去重。
    缺少可靠旧边界时保留 ``None``，由调用方采用保守策略。
    """
    segments = []
    current = db.get(SessionPersona, persona_id)
    child_session = None
    visited = set()

    while current is not None and current.id not in visited:
        visited.add(current.id)
        session = db.get(Session, current.session_id)
        if session is None:
            break

        copied_boundary_message_id = None
        if session.parent_session_id is not None and session.fork_message_id is not None:
            first_message = (
                db.query(ChatMessage)
                .filter(ChatMessage.session_id == session.id)
                .order_by(ChatMessage.id.asc())
                .first()
            )
            fork_message = db.get(ChatMessage, session.fork_message_id)
            if (
                first_message is not None
                and fork_message is not None
                and first_message.role == fork_message.role
                and first_message.content == fork_message.content
            ):
                copied_boundary_message_id = first_message.id

        segments.append({
            "persona_id": current.id,
            "session_id": session.id,
            "through_message_id": (
                child_session.fork_message_id if child_session is not None else None
            ),
            "copied_boundary_message_id": copied_boundary_message_id,
        })
        child_session = session
        if current.parent_persona_id is None:
            break
        current = db.get(SessionPersona, current.parent_persona_id)

    return segments
