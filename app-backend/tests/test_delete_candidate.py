"""
候选消息删除与好感度回滚单元测试脚本
"""

import os
import sys
import io

# 强制在 Windows 终端下使用 UTF-8 编码输出以支持 Emoji 和中文
if sys.platform.startswith('win'):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# 将当前目录的父目录加入 python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SessionLocal
from core import Base, engine
from core.models import Character, Session, SessionPersona, ChatMessage, MessageRole
from routers.sessions import delete_message

def run_candidate_delete_test():
    print("=" * 60)
    print("🚀 开始运行候选消息删除好感度影响单元测试...")
    print("=" * 60)

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # 1. 创建基础数据
        character = Character(
            name="候选测试姬",
            description="用于测试候选版本消息删除的测试助理。",
            first_mes="你好！"
        )
        db.add(character)
        db.flush()

        session = Session(title="候选测试会话")
        db.add(session)
        db.flush()

        persona = SessionPersona(
            session_id=session.id,
            character_id=character.id,
            affection_score=50,
            current_mood="平静"
        )
        db.add(persona)
        db.flush()

        # 2. 写入用户消息
        user_msg = ChatMessage(
            session_id=session.id,
            role=MessageRole.user,
            content="你在干嘛呢？",
            is_active=True
        )
        db.add(user_msg)
        db.flush()

        # 3. 写入当前激活的回复 (好感度增加 5，总好感度变为 55)
        active_reply = ChatMessage(
            session_id=session.id,
            role=MessageRole.assistant,
            content="我正在等你的消息呀！",
            parent_id=user_msg.id,
            affection_change=5,
            emotion_tag="开心",
            is_active=True
        )
        db.add(active_reply)
        persona.affection_score += 5
        persona.current_mood = "开心"
        db.flush()

        # 4. 写入未激活的候选回复 (好感度应增加 10，但因为未激活，总好感度仍保持 55)
        inactive_reply = ChatMessage(
            session_id=session.id,
            role=MessageRole.assistant,
            content="我正在发呆呢。",
            parent_id=user_msg.id,
            affection_change=10,
            emotion_tag="发呆",
            is_active=False
        )
        db.add(inactive_reply)
        db.commit()

        # 检查初始状态
        print(f"初始状态: 好感度 = {persona.affection_score} (预期 55), 心情 = {persona.current_mood} (预期 开心)")
        assert persona.affection_score == 55, "初始好感度不符合预期"

        # 5. 删除【未激活】的候选回复
        print("\n[动作] 删除【未激活】的候选回复...")
        delete_message(inactive_reply.id, db)
        
        # 刷新 Persona 状态
        db.refresh(persona)
        print(f"删除后状态: 好感度 = {persona.affection_score} (预期仍为 55), 心情 = {persona.current_mood} (预期仍为 开心)")
        
        # 如果有 Bug，此处好感度会错误的被减去 10 变成 45
        assert persona.affection_score == 55, f"❌ 错误: 删除未激活的候选消息导致好感度被扣减为 {persona.affection_score}!"
        print("  ✅ 成功验证: 删除未激活的消息没有对好感度产生错误影响！")

    finally:
        # 清理
        db.rollback()
        db.close()


if __name__ == "__main__":
    try:
        run_candidate_delete_test()
    except AssertionError as e:
        print(str(e))
        sys.exit(1)
