"""
会话生命周期与继承链重连服务
"""

import json
from sqlalchemy.orm import Session as DBSession
from core.models import Session, SessionPersona, MemoryChunk, OutboxJob, ChatMessage


def safe_delete_session(session_id: int, db: DBSession) -> dict:
    """
    安全删除 Session：重连继承链 -> 收集向量/音频并入库发件箱任务 -> 最终提交。

    当删除继承链中间的节点时（如 s1 -> s2 -> s3 中删除 s2），
    自动将子节点重连到父节点，避免继承链断裂。

    安全顺序：
      1. 重连子 Session / Persona 的继承关系
      2. 搜集要删除的 ChromaDB 向量 doc_id 和本地音频文件路径
      3. db.delete(session) + db.flush() → 验证所有 FK 约束
      4. 约束验证通过后，将异步清理任务写入发件箱表
      5. db.commit() 最终提交
    """
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

    # Step 2: 重连子 Persona + 收集 ChromaDB 和音频清理所需信息
    persona = session.persona
    persona_id = None
    character_id = None
    doc_ids = []

    if persona:
        persona_id = persona.id
        character_id = persona.character_id
        parent_persona_id = persona.parent_persona_id

        # 收集属于该 persona 的所有 MemoryChunk 对应的向量 ID
        chunks = db.query(MemoryChunk).filter(
            MemoryChunk.persona_id == persona.id
        ).all()
        doc_ids = [c.chroma_doc_id for c in chunks if c.chroma_doc_id]

        children_personas = db.query(SessionPersona).filter(
            SessionPersona.parent_persona_id == persona.id
        ).all()

        for child_p in children_personas:
            child_p.parent_persona_id = parent_persona_id

    # 收集当前会话中所有的消息音频路径
    messages_with_audio = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id,
        ChatMessage.audio_path.isnot(None),
        ChatMessage.audio_path != ""
    ).all()
    audio_paths = [m.audio_path for m in messages_with_audio]

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

    # Step 4: SQLite 验证通过，向发件箱写入清理 ChromaDB 的任务
    if persona_id is not None and character_id is not None and doc_ids:
        try:
            payload = {
                "character_id": character_id,
                "doc_ids": doc_ids
            }
            job = OutboxJob(
                task_type="delete_vector",
                payload=json.dumps(payload)
            )
            db.add(job)
            result["memories_deleted"] = len(doc_ids)
            print(f"[INFO] Outbox: 已入库 session_id={session_id} persona_id={persona_id} 的 {len(doc_ids)} 条记忆删除任务")
        except Exception as e:
            print(f"[WARN] 写入发件箱向量清理任务失败: {e}")

    # 向发件箱写入清理本地音频的任务
    if audio_paths:
        try:
            payload = {
                "file_paths": audio_paths
            }
            job = OutboxJob(
                task_type="delete_audio",
                payload=json.dumps(payload)
            )
            db.add(job)
            print(f"[INFO] Outbox: 已入库 session_id={session_id} 的 {len(audio_paths)} 个语音文件删除任务")
        except Exception as e:
            print(f"[WARN] 写入发件箱语音文件清理任务失败: {e}")

    # Step 5: 最终提交
    db.commit()

    print(f"[INFO] safe_delete_session: 已安全删除 Session {session_id}，"
          f"重连了 {result['relinked_children']} 个子节点，"
          f"入库清理了 {result['memories_deleted']} 条记忆")

    return result

