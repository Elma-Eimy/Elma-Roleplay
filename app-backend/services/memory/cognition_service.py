"""维护角色对自身、世界和用户的宏观认知状态。"""

from typing import Optional
import logging

from sqlalchemy import text
from sqlalchemy.orm import Session as DBSession

from core.config import settings
from services.infrastructure.model_capabilities import auxiliary_controls
from services.conversation.session_access import get_single_persona
from core.models import ChatMessage
from services.infrastructure.llm_provider import get_llm_provider


logger = logging.getLogger(__name__)


def _version(persona):
    return (persona.session_id, persona.character_id, persona.parent_persona_id,
            persona.session.parent_session_id, persona.session.fork_message_id,
            persona.cognition_state, persona.last_cognition_update_msg_id, persona.character.name)


def _sources(persona, db, through=None):
    query = db.query(ChatMessage.id, ChatMessage.role, ChatMessage.content, ChatMessage.parent_id).filter(
        ChatMessage.session_id == persona.session_id, ChatMessage.is_active == True,
    )
    if persona.last_cognition_update_msg_id is not None:
        query = query.filter(ChatMessage.id > persona.last_cognition_update_msg_id)
    if through is not None:
        query = query.filter(ChatMessage.id <= through)
    return tuple(tuple(row) for row in query.order_by(ChatMessage.id).all())


def get_cognition_unseen_count(
    persona_id: int,
    session_id: int,
    db: DBSession,
) -> int:
    """返回自上次认知更新以来的新消息数量。"""
    persona = get_single_persona(persona_id, db)
    if not persona:
        return 0

    query = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id,
        ChatMessage.is_active == True,
    )
    if persona.last_cognition_update_msg_id is not None:
        query = query.filter(ChatMessage.id > persona.last_cognition_update_msg_id)

    return query.count()


def update_cognition_state(persona_id: int, db: DBSession) -> Optional[str]:
    """根据新增对话更新 ``SessionPersona.cognition_state``。"""
    if db.new or db.dirty or db.deleted:
        raise ValueError("认知更新不能提交调用方尚未保存的修改")
    persona = get_single_persona(persona_id, db)
    if not persona:
        print(f"[WARN] update_cognition_state: Persona {persona_id} 不存在")
        return None

    # 显式读取事务让认知版本、分支边界和消息来自同一份 SQLite 快照。
    db.commit()
    db.execute(text("BEGIN"))
    db.expire_all()
    persona = get_single_persona(persona_id, db)
    if persona is None:
        db.rollback()
        return None
    expected_version = _version(persona)
    old_cognition = persona.cognition_state or "（尚未建立认知）"
    recent_messages = _sources(persona, db)
    if not recent_messages:
        current = persona.cognition_state
        db.rollback()
        return current

    last_msg_id = recent_messages[-1][0]
    chat_text = "".join(
        f"{'User' if role.value == 'user' else 'Assistant'}: {content}\n"
        for _, role, content, _ in recent_messages
    )
    character_name = persona.character.name
    system_prompt = f"""你是一个角色认知更新专家。你需要基于角色当前的认知状态 and 最近的对话，生成更新后的认知摘要。

认知摘要应当描述"角色（名字为：{character_name}）此刻对自己、世界和用户的整体认知"，它将直接组装进角色的 System Prompt。

要求：
1. 保留旧认知中仍然有效的部分
2. 融入新对话中产生的重要认知变化
3. 必须使用角色（名字为：{character_name}）自己的第一人称视角描述（如"作为 {character_name}，我认为..."、"我知道..."、"我感觉..."），禁止使用第三人称（如"他"、"她"、"{character_name}认为..."），以使生成的内容能够作为 {character_name} 的第一人称心声无缝融入扮演设定。
4. 保持现代、克制、客观的心理画像表述，聚焦于关系定位、情感依恋、信任度与既定事实认知；严禁使用市井民俗俚语、民国或明清旧白话口癖（如"方才"、"没个消停"、"自个儿"、"心里才不凉"等）以及戏剧化的怨妇独白，防止污染后续对话文风。
5. 仅归纳已被角色实质接纳的当前关系与心理状态，不把对话中过渡性的修辞推拉或羞怯反应固化为永久抗拒原则。
6. 控制在 {settings.APP_COGNITION_MAX_WORDS} 字以内
7. 直接返回纯文本，不要使用 JSON 或 markdown 格式"""
    user_content = f"""当前认知状态：
{old_cognition}

最近的对话：
{chat_text}

请生成更新后的认知摘要："""

    # 在外部模型调用前结束当前事务，避免长时间占用 SQLite 写锁。
    db.commit()

    try:
        provider = get_llm_provider()
        response = provider.generate(
            model=settings.LLM_MEMORY_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content},
            ],
            **auxiliary_controls("memory", settings.LLM_MEMORY_TEMPERATURE),
        )
        new_cognition = response.choices[0].message.content.strip()
        if not new_cognition:
            raise ValueError("认知更新结果为空")

        # 先取得写权再校验，禁止其他写入穿过校验与发布之间的窗口。
        db.execute(text("BEGIN IMMEDIATE"))
        db.expire_all()
        persona = get_single_persona(persona_id, db)
        if (persona is None or _version(persona) != expected_version
                or _sources(persona, db, last_msg_id) != recent_messages):
            db.rollback()
            logger.info("cognition_update_discarded persona_id=%s", persona_id)
            return None
        persona.cognition_state = new_cognition
        persona.last_cognition_update_msg_id = last_msg_id
        db.commit()

        print(f"[INFO] cognition_state 已更新 (persona_id={persona_id})")
        return new_cognition
    except Exception as exc:
        db.rollback()
        logger.warning("cognition_update_failed persona_id=%s error_type=%s", persona_id, type(exc).__name__)
        return None
