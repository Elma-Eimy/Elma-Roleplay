"""
会话生命周期与继承链重连服务
"""

from sqlalchemy.orm import Session as DBSession
from core.models import Session, SessionPersona


def safe_delete_session(session_id: int, db: DBSession) -> dict:
    """
    安全删除 Session：重连继承链 -> 验证 SQLite -> 清理 ChromaDB -> 提交。

    当删除继承链中间的节点时（如 s1 -> s2 -> s3 中删除 s2），
    自动将子节点重连到父节点，避免继承链断裂。

    安全顺序：
      1. 重连子 Session / Persona 的继承关系
      2. db.delete(session) + db.flush() → 验证所有 FK 约束
      3. 约束验证通过后，才清理 ChromaDB 数据
      4. db.commit() 最终提交

    如果 Step 2 的 flush 失败（FK 约束冲突等），ChromaDB 完全不受影响。

    返回：{"deleted_session_id": int, "relinked_children": int, "memories_deleted": int}
    """
    # 动态导入以防循环依赖
    from services.memory_manager import get_character_collection

    session = db.get(Session, session_id)
    if not session:
        raise ValueError(f"Session {session_id} 不存在")

    parent_session_id = session.parent_session_id
    result = {
        "deleted_session_id": session_id,
        "relinked_children": 0,
        "memories_deleted": 0,
    }

    # Step 1: 重连子 Session
    children_sessions = db.query(Session).filter(
        Session.parent_session_id == session_id
    ).all()

    for child in children_sessions:
        child.parent_session_id = parent_session_id
        result["relinked_children"] += 1

    # Step 2: 重连子 Persona + 收集 ChromaDB 清理所需信息
    persona = session.persona
    persona_id = None
    character_id = None

    if persona:
        persona_id = persona.id
        character_id = persona.character_id
        parent_persona_id = persona.parent_persona_id

        children_personas = db.query(SessionPersona).filter(
            SessionPersona.parent_persona_id == persona.id
        ).all()

        for child_p in children_personas:
            child_p.parent_persona_id = parent_persona_id

    # Step 3: 先验证 SQLite 操作（flush 但不 commit，检查所有 FK 约束）
    db.delete(session)
    try:
        db.flush()
    except Exception as e:
        db.rollback()
        print(f"==========================================")
        print(f"[ERROR] safe_delete_session: SQLite 约束验证失败，已回滚")
        print(f"[ERROR] 错误类型: {type(e).__name__}")
        print(f"[ERROR] 错误详情: {e}")
        print(f"==========================================")
        raise ValueError(f"Session {session_id} 删除失败（SQLite 约束冲突）: {e}")

    # Step 4: SQLite 验证通过，安全清理 ChromaDB
    if persona_id is not None and character_id is not None:
        try:
            collection = get_character_collection(character_id)
            existing = collection.get(
                where={"persona_id": persona_id},
                include=[],
            )
            chroma_count = len(existing["ids"]) if existing and existing.get("ids") else 0

            if chroma_count > 0:
                collection.delete(where={"persona_id": persona_id})
                result["memories_deleted"] = chroma_count
                print(f"[INFO] ChromaDB: 已删除 persona_id={persona_id} 的 {chroma_count} 条记忆")
        except Exception as e:
            # ChromaDB 清理失败不阻塞 SQLite 提交
            # 孤儿向量数据可接受（persona 已不存在，不会被检索到）
            print(f"[WARN] ChromaDB 清理失败（SQLite 将继续提交，孤儿数据不影响检索）: {e}")

    # Step 5: 最终提交
    db.commit()

    print(f"[INFO] safe_delete_session: 已安全删除 Session {session_id}，"
          f"重连了 {result['relinked_children']} 个子节点，"
          f"清理了 {result['memories_deleted']} 条记忆")

    return result
