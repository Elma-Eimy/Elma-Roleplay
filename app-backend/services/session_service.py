"""
会话生命周期与继承链重连服务

本服务承载角色扮演记忆系统中的“会话（Session）”核心业务逻辑，具体包括：
1. 会话生命周期的安全删除与子会话关系的安全重连（重连继承链以防止 timeline 损坏）。
2. 新建会话（全新起步 / 从父会话继承好感度及认知状态的深拷贝复制）。
3. 角色开场白注入与利用正则表达式的动态场景（Scenario）/地点解析算法。
4. 消息的删除与状态回滚（包括好感度、心情及 Swipe 多回复候选的向前回溯与替补激活）。
5. 消息删除时，异步语音文件的发件箱队列任务注册。
"""

import json
import re
import os
from typing import Optional
from sqlalchemy.orm import Session as DBSession
from sqlalchemy.sql import func
from core.models import (
    Session as SessionModel, 
    SessionPersona, 
    MemoryChunk, 
    OutboxJob, 
    ChatMessage, 
    Character,
    MessageRole
)
from core.config import settings


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
    session = db.get(SessionModel, session_id)
    if not session:
        raise ValueError(f"Session {session_id} 不存在")

    parent_session_id = session.parent_session_id
    parent_fork_message_id = session.fork_message_id
    result = {
        "deleted_session_id": session_id,
        "relinked_children": 0,
        "memories_deleted": 0,
    }

    # Step 1: 重连子 Session
    # 使用批量 UPDATE 在删除旧父节点前直接落下新的外键，规避自关联 ORM
    # backref 在同一次 flush 中产生循环依赖。
    result["relinked_children"] = db.query(SessionModel).filter(
        SessionModel.parent_session_id == session_id
    ).update(
        {
            SessionModel.parent_session_id: parent_session_id,
            # 中间节点删除后，子会话相对于新父会话（原祖父会话）的安全边界，
            # 应继承被删除节点当初的分叉点。若删除根节点则清空边界。
            SessionModel.fork_message_id: (
                parent_fork_message_id if parent_session_id is not None else None
            ),
        },
        synchronize_session=False,
    )

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

        db.query(SessionPersona).filter(
            SessionPersona.parent_persona_id == persona.id
        ).update(
            {SessionPersona.parent_persona_id: parent_persona_id},
            synchronize_session=False,
        )

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


def create_session_service(
    character_id: int,
    parent_session_id: Optional[int],
    title: str,
    greeting_index: Optional[int],
    start_message_id: Optional[int],
    db: DBSession
) -> dict:
    """
    业务逻辑：创建新的对话会话。

    - 不指定 parent_session_id：从角色蓝图全新创建（affection=0，无认知）
    - 指定 parent_session_id：从父会话继承（复制好感度、认知状态、场景、心情）

    自动在非继承（全新）模式下，插入角色的 first_mes 或 alternate_greetings 作为第一条 AI 消息。
    在继承模式下，复制由 start_message_id 指定的分支起步消息。
    """
    # 验证角色存在
    character = db.get(Character, character_id)
    if not character:
        raise ValueError("Character not found")

    # 创建 SessionModel 实体
    session = SessionModel(
        parent_session_id=parent_session_id,
        title=title,
    )
    db.add(session)
    db.flush()  # 获取分配的 session.id

    # 创建并绑定 SessionPersona 实体（管理好感度与心情等动态运行状态）
    if parent_session_id:
        # ── 继承/分支模式 ──
        parent_session = db.get(SessionModel, parent_session_id)
        if not parent_session or not parent_session.persona:
            db.rollback()
            raise ValueError("Parent session or its persona not found")

        parent_persona = parent_session.persona
        # 验证 character_id 一致
        if parent_persona.character_id != character_id:
            db.rollback()
            raise ValueError("character_id must match the parent session's character")

        persona = SessionPersona(
            session_id=session.id,
            character_id=parent_persona.character_id,
            parent_persona_id=parent_persona.id,
            affection_score=parent_persona.affection_score,
            cognition_state=parent_persona.cognition_state,
            current_scenario_override=parent_persona.current_scenario_override,
            current_mood=parent_persona.current_mood,
        )
    else:
        # ── 全新模式 ──
        persona = SessionPersona(
            session_id=session.id,
            character_id=character_id,
            parent_persona_id=None,
            affection_score=0,
        )

    db.add(persona)

    # 仅在非继承（全新）模式下，插入第一条 AI 消息作为开场白
    if not parent_session_id:
        first_content = character.first_mes
        scenario_override = None

        if greeting_index is not None and character.extensions:
            try:
                ext = json.loads(character.extensions) if isinstance(character.extensions, str) else character.extensions
                alt_greetings = ext.get("alternate_greetings", [])
                if 0 <= greeting_index < len(alt_greetings):
                    first_content = alt_greetings[greeting_index]
            except Exception as e:
                print(f"[WARN] Failed to parse alternate greeting: {e}")

        # 强兼容性场景/地点解析算法
        if first_content:
            try:
                # 规则 1：匹配以常见地点、地图、交通、建筑类 Emoji 开头的三级标题（置于首位以防关键字干扰）
                # 例如：### 📍 Abandoned Warehouse, ### 🗺️ Tokyo Port | Night, ### 🏠 Safehouse
                emoji_match = re.search(
                    r'###\s*(?:[📍🗺️🌐⚔️🏠🏢🏫🌄🌅🌇🌆🌃🧭🎪🎡🎢])\s*([^\n|#]+)',
                    first_content
                )
                if emoji_match:
                    scenario_override = emoji_match.group(1).strip()
                
                # 规则 2：匹配高优先级地点/场景关键字（支持 ### 标题、[中括号] 或纯文本开头）
                # 例如：### Location: Shinjuku | Night, [地点: 学校], Scene: Bar
                if not scenario_override:
                    loc_kw_match = re.search(
                        r'(?:###\s*|\[\s*|\b)(?:Location|Scene|地点|当前地点)\s*[:：]\s*([^\n|#\]\)]+)',
                        first_content,
                        re.IGNORECASE
                    )
                    if loc_kw_match:
                        scenario_override = loc_kw_match.group(1).strip()
                
                # 规则 3：低优先级退避规则：匹配 Scenario / 场景关键字
                # 例如：### Scenario: Fighting in Shinjuku
                if not scenario_override:
                    scen_kw_match = re.search(
                        r'(?:###\s*|\[\s*|\b)(?:Scenario|Scenario\s*\d+|场景|当前场景)\s*[:：]\s*([^\n|#\]\)]+)',
                        first_content,
                        re.IGNORECASE
                    )
                    if scen_kw_match:
                        scenario_override = scen_kw_match.group(1).strip()
            except Exception as e:
                print(f"[WARN] Failed to extract location from opening message: {e}")

        if scenario_override:
            persona.current_scenario_override = scenario_override

        if first_content:
            first_message = ChatMessage(
                session_id=session.id,
                role=MessageRole.assistant,
                content=first_content,
                emotion_tag="平静",
                affection_change=0,
                parent_id=None,
                is_active=True,
            )
            db.add(first_message)
    else:
        # ── 继承/分支模式 ──
        # 根据传参或退避逻辑，复制首条触发分支的消息
        start_message = None
        if start_message_id is not None:
            start_message = db.query(ChatMessage).filter(
                ChatMessage.id == start_message_id,
                ChatMessage.session_id == parent_session_id
            ).first()

            # 调用方明确指定了分叉点时，不能静默改用另一条消息，否则会生成
            # 与用户选择不一致且难以察觉的时间线。
            if not start_message:
                db.rollback()
                raise ValueError(
                    f"Start message {start_message_id} does not belong to parent session {parent_session_id}"
                )
        
        if not start_message:
            # 退避策略：获取父会话最后一条激活的聊天消息
            start_message = (
                db.query(ChatMessage)
                .filter(
                    ChatMessage.session_id == parent_session_id,
                    ChatMessage.is_active == True
                )
                .order_by(ChatMessage.id.desc())
                .first()
            )

        if start_message:
            session.fork_message_id = start_message.id
            first_message = ChatMessage(
                session_id=session.id,
                role=start_message.role,
                content=start_message.content,
                emotion_tag=start_message.emotion_tag,
                affection_change=start_message.affection_change,
                audio_path=start_message.audio_path,
                parent_id=None,
                is_active=True,
            )
            db.add(first_message)

    db.commit()
    db.refresh(session)

    return {
        "message": "Session created successfully",
        "session_id": session.id,
        "persona_id": persona.id,
        "character_id": character_id,
        "inherited": parent_session_id is not None,
        "fork_message_id": session.fork_message_id,
        "title": session.title,
    }


def delete_message_service(message_id: int, db: DBSession) -> dict:
    """
    业务逻辑：删除单条聊天消息，并执行好感度与心情回滚缓冲，同时提供未提纯和认知指针的安全降级保护。
    """
    message = db.get(ChatMessage, message_id)
    if not message:
        raise ValueError("Message not found")

    deleted_id = message.id
    session_id = message.session_id

    # 1. 查找该会话关联的 SessionPersona 实体以执行状态回滚
    persona = db.query(SessionPersona).filter(
        SessionPersona.session_id == session_id
    ).first()

    if persona:
        # ── 1a. 好感度与心情回退 & Swipe 候选回退处理 ──
        if message.role == MessageRole.assistant:
            if message.is_active:
                sibling = db.query(ChatMessage).filter(
                    ChatMessage.session_id == session_id,
                    ChatMessage.role == MessageRole.assistant,
                    ChatMessage.parent_id == message.parent_id,
                    ChatMessage.id != message_id
                ).order_by(ChatMessage.id.desc()).first()

                if sibling:
                    # 激活替补候选版本
                    sibling.is_active = True
                    old_change = message.affection_change or 0
                    new_change = sibling.affection_change or 0
                    persona.affection_score = persona.affection_score - old_change + new_change
                    persona.affection_score = max(0, min(100, persona.affection_score))
                    persona.current_mood = sibling.emotion_tag or "平静"
                else:
                    # 没有候选替补，常规回滚
                    if message.affection_change is not None:
                        persona.affection_score -= message.affection_change
                        persona.affection_score = max(0, persona.affection_score)

                    # ── 1b. 情绪状态回滚 ──
                    # 查找在当前被删消息时间线之前的最近一条 assistant 消息
                    prev_assistant_msg = db.query(ChatMessage).filter(
                        ChatMessage.session_id == session_id,
                        ChatMessage.role == MessageRole.assistant,
                        ChatMessage.id < message_id
                    ).order_by(ChatMessage.id.desc()).first()

                    if prev_assistant_msg:
                        persona.current_mood = prev_assistant_msg.emotion_tag or "平静"
                    else:
                        persona.current_mood = "平静"
            else:
                # 若被删除的是非激活候选版本，直接跳过好感度与心情回滚
                pass

        elif message.role == MessageRole.user:
            # 找到将被级联删除的、当前处于激活状态的 AI 回复
            active_child = db.query(ChatMessage).filter(
                ChatMessage.session_id == session_id,
                ChatMessage.role == MessageRole.assistant,
                ChatMessage.parent_id == message_id,
                ChatMessage.is_active == True
            ).first()
            if active_child and active_child.affection_change is not None:
                persona.affection_score -= active_child.affection_change
                persona.affection_score = max(0, persona.affection_score)
            
            # 回滚情绪状态至上一轮对话的最近一条 AI 消息
            prev_assistant_msg = db.query(ChatMessage).filter(
                ChatMessage.session_id == session_id,
                ChatMessage.role == MessageRole.assistant,
                ChatMessage.id < message_id
            ).order_by(ChatMessage.id.desc()).first()
            if prev_assistant_msg:
                persona.current_mood = prev_assistant_msg.emotion_tag or "平静"
            else:
                persona.current_mood = "平静"

        # ── 1c. 记忆提纯与认知指针安全降级保护 ──
        # 如果被删的消息 ID 刚好等于分界指针，安全寻找上一条消息 ID 进行向前递减
        if persona.last_summarized_msg_id == message_id:
            prev_msg = db.query(ChatMessage).filter(
                ChatMessage.session_id == session_id,
                ChatMessage.id < message_id
            ).order_by(ChatMessage.id.desc()).first()
            persona.last_summarized_msg_id = prev_msg.id if prev_msg else None

        if persona.last_cognition_update_msg_id == message_id:
            prev_msg = db.query(ChatMessage).filter(
                ChatMessage.session_id == session_id,
                ChatMessage.id < message_id
            ).order_by(ChatMessage.id.desc()).first()
            persona.last_cognition_update_msg_id = prev_msg.id if prev_msg else None

    # 2. 收集音频文件路径以便异步清理
    audio_paths = []
    if message.audio_path:
        audio_paths.append(message.audio_path)
    if message.role == MessageRole.user:
        # 收集将被级联删除的所有子消息的音频路径
        children = db.query(ChatMessage).filter(
            ChatMessage.parent_id == message_id
        ).all()
        for child in children:
            if child.audio_path:
                audio_paths.append(child.audio_path)

    # 3. 物理删除消息记录
    db.delete(message)

    # 4. 写入发件箱语音文件清理任务
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
            print(f"[INFO] Outbox: 已入库消息关联 of {len(audio_paths)} 个语音文件删除任务")
        except Exception as e:
            print(f"[WARN] delete_message_service 写入发件箱任务失败: {e}")

    session = db.get(SessionModel, session_id)
    if session:
        session.updated_at = func.now()
    db.commit()

    return {
        "message": "Message deleted and state rolled back successfully",
        "message_id": deleted_id,
        "affection_score": persona.affection_score if persona else None,
        "current_mood": persona.current_mood if persona else None
    }


def get_session_history_with_inheritance(
    session_id: int, 
    db: DBSession, 
    limit: int, 
    before_id: int = None
) -> list[ChatMessage]:
    """
    获取指定会话的聊天历史记录。
    按照时间正序排列（最旧的在前面，最新的在后面）。
    注：根据对齐后的颗粒度要求，开启子会话时不再合并父会话的原始消息记录，
    以便子会话独立于父会话重新起步，因此此处仅拉取当前会话的消息，不再递归向上追溯。
    """
    query = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id,
        ChatMessage.is_active == True
    )
    if before_id is not None:
        query = query.filter(ChatMessage.id < before_id)

    messages = (
        query.order_by(ChatMessage.id.desc())
        .limit(limit)
        .all()
    )
    messages.reverse()  # 反转以恢复时间正序
    return messages


def save_chat_response(
    session_id: int,
    persona_id: int,
    user_msg_id: int,
    reply_text: str,
    reasoning_content: str,
    emotion_tag: str,
    affection_change: int,
    is_regenerate: bool,
    old_reply_id: Optional[int],
    db: DBSession
) -> tuple[int, int, list[dict]]:
    """
    业务逻辑：保存 AI 回复消息，更新 Persona 好感度与心情，重置/更新 Swipe 历史候选列表，并提交事务。
    
    Args:
        session_id: 当前会话 ID
        persona_id: 会话对应的 Persona ID
        user_msg_id: 触发该回复的用户消息 ID
        reply_text: AI 生成的回复正文
        reasoning_content: AI 的思考过程文本 (如果有)
        emotion_tag: AI 的情绪分类标签
        affection_change: 本轮好感度增减量值
        is_regenerate: 是否是重新生成 (Swipe) 模式
        old_reply_id: 要被失效替换的旧回复消息 ID (仅 is_regenerate 为 True 且旧回复存在时非空)
        db: SQLAlchemy 数据库会话
        
    Returns:
        元组 (ai_message_id, final_affection_score, candidates_list)
    """
    p = db.get(SessionPersona, persona_id)
    if not p:
        raise ValueError("SessionPersona not found")

    # Swipe 候选支持：此时才真正使旧回复失效，并扣减好感度评分以保持事务原子性
    if is_regenerate and old_reply_id:
        db_old_reply = db.get(ChatMessage, old_reply_id)
        if db_old_reply:
            db_old_reply.is_active = False
            if db_old_reply.affection_change is not None:
                p.affection_score -= db_old_reply.affection_change

    # 实例化新的 AI 助手回复消息
    ai_msg = ChatMessage(
        session_id=session_id,
        role=MessageRole.assistant,
        content=reply_text,
        reasoning_content=reasoning_content,
        emotion_tag=emotion_tag,
        affection_change=affection_change,
        parent_id=user_msg_id,
        is_active=True
    )
    db.add(ai_msg)

    # 累加好感度分数并应用上限规范限制 (0 ~ 100)
    p.affection_score += affection_change
    p.affection_score = max(0, min(100, p.affection_score))
    p.current_mood = emotion_tag

    # Touch Session 更新时间戳
    session_obj = db.get(SessionModel, session_id)
    if session_obj:
        session_obj.updated_at = func.now()

    db.commit()
    db.refresh(ai_msg)
    db.refresh(p)

    # 查询此轮对话的用户消息下的所有候选回复列表
    candidates = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id,
        ChatMessage.role == MessageRole.assistant,
        ChatMessage.parent_id == user_msg_id
    ).order_by(ChatMessage.id).all()

    candidates_list = [
        {
            "id": c.id,
            "role": c.role.value,
            "content": c.content,
            "reasoning_content": c.reasoning_content,
            "emotion_tag": c.emotion_tag,
            "affection_change": c.affection_change,
            "created_at": c.created_at.isoformat() if c.created_at else None,
            "audio_path": c.audio_path,
        }
        for c in candidates
    ]

    return ai_msg.id, p.affection_score, candidates_list
