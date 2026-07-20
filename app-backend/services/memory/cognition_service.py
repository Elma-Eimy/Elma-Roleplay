"""维护角色对自身、世界和用户的宏观认知状态。"""

from typing import Optional

from sqlalchemy.orm import Session as DBSession

from core.config import settings
from core.models import ChatMessage, SessionPersona
from services.infrastructure.llm_provider import get_llm_provider


def get_cognition_unseen_count(
    persona_id: int,
    session_id: int,
    db: DBSession,
) -> int:
    """返回自上次认知更新以来的新消息数量。"""
    persona = db.get(SessionPersona, persona_id)
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
    persona = db.get(SessionPersona, persona_id)
    if not persona:
        print(f"[WARN] update_cognition_state: Persona {persona_id} 不存在")
        return None

    session_id = persona.session_id
    old_cognition = persona.cognition_state or "（尚未建立认知）"
    query = db.query(ChatMessage).filter(
        ChatMessage.session_id == session_id,
        ChatMessage.is_active == True,
    )
    if persona.last_cognition_update_msg_id is not None:
        query = query.filter(ChatMessage.id > persona.last_cognition_update_msg_id)

    recent_messages = query.order_by(ChatMessage.id).all()
    if not recent_messages:
        return persona.cognition_state

    last_msg_id = recent_messages[-1].id
    chat_text = "".join(
        f"{'User' if msg.role.value == 'user' else 'Assistant'}: {msg.content}\n"
        for msg in recent_messages
    )
    character_name = persona.character.name
    system_prompt = f"""你是一个角色认知更新专家。你需要基于角色当前的认知状态 and 最近的对话，生成更新后的认知摘要。

认知摘要应当描述"角色（名字为：{character_name}）此刻对自己、世界和用户的整体认知"，它将直接组装进角色的 System Prompt。

要求：
1. 保留旧认知中仍然有效的部分
2. 融入新对话中产生的重要认知变化
3. 必须使用角色（名字为：{character_name}）自己的第一人称视角描述（如"作为 {character_name}，我认为..."、"我知道..."、"我感觉..."），禁止使用第三人称（如"他"、"她"、"{character_name}认为..."），以使生成的内容能够作为 {character_name} 的第一人称心声无缝融入扮演设定。
4. 控制在 {settings.APP_COGNITION_MAX_WORDS} 字以内
5. 直接返回纯文本，不要使用 JSON 或 markdown 格式"""
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
            temperature=settings.LLM_MEMORY_TEMPERATURE,
        )
        new_cognition = response.choices[0].message.content.strip()

        persona = db.get(SessionPersona, persona_id)
        if persona:
            persona.cognition_state = new_cognition
            persona.last_cognition_update_msg_id = last_msg_id
            db.commit()

        print(f"[INFO] cognition_state 已更新 (persona_id={persona_id})")
        return new_cognition
    except Exception as exc:
        print("==========================================")
        print("[ERROR] update_cognition_state: LLM 调用失败")
        print(f"[ERROR] 错误类型: {type(exc).__name__}")
        print(f"[ERROR] 错误详情: {exc}")
        print("==========================================")
        return None
