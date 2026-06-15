import os
import sys

# Add parent directory to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SessionLocal, engine
from core import Base, models
from core.models import MessageRole
from schemas import SessionCreate
from routers.sessions import create_session

def run_tests():
    print("==================================================")
    print(" 开始运行分支起始消息 (Branch Start Message) 单元测试...")
    print("==================================================")

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # 1. 清理已有的测试数据
        test_char_name = "分支测试助手"
        db.query(models.Character).filter(models.Character.name == test_char_name).delete()
        db.commit()

        # 2. 创建测试角色
        char = models.Character(
            name=test_char_name,
            description="用于分支测试的角色",
            first_mes="你好！我是分支测试角色。",
        )
        db.add(char)
        db.commit()
        db.refresh(char)
        print(f"[SUCCESS] 创建测试角色: {char.name} (ID: {char.id})")

        # 3. 创建父会话
        req_parent = SessionCreate(
            character_id=char.id,
            title="父会话"
        )
        res_parent = create_session(req_parent, db)
        parent_session_id = res_parent["session_id"]
        print(f"[SUCCESS] 创建父会话 ID: {parent_session_id}")

        # 4. 手动插入几条消息到父会话
        msg1 = models.ChatMessage(
            session_id=parent_session_id,
            role=MessageRole.user,
            content="用户消息1：我想讨论平行宇宙。",
            emotion_tag=None,
            affection_change=0,
            is_active=True
        )
        msg2 = models.ChatMessage(
            session_id=parent_session_id,
            role=MessageRole.assistant,
            content="AI回复1：平行宇宙是一个非常有趣的话题！",
            emotion_tag="高兴",
            affection_change=5,
            is_active=True
        )
        msg3 = models.ChatMessage(
            session_id=parent_session_id,
            role=MessageRole.user,
            content="用户消息2：我们再聊聊分叉。",
            emotion_tag=None,
            affection_change=0,
            is_active=True
        )
        db.add(msg1)
        db.add(msg2)
        db.add(msg3)
        db.commit()
        db.refresh(msg1)
        db.refresh(msg2)
        db.refresh(msg3)
        print(f"[SUCCESS] 插入测试消息: msg1={msg1.id}, msg2={msg2.id}, msg3={msg3.id}")

        # 5. 测试场景 A：指定 start_message_id 分支 (从 msg2 处分支)
        print("\n--- 测试场景 A: 指定消息分叉 ---")
        req_branch_a = SessionCreate(
            character_id=char.id,
            parent_session_id=parent_session_id,
            title="分支 A",
            start_message_id=msg2.id
        )
        res_branch_a = create_session(req_branch_a, db)
        branch_a_id = res_branch_a["session_id"]
        
        # 验证分支 A 的消息
        msgs_a = db.query(models.ChatMessage).filter(
            models.ChatMessage.session_id == branch_a_id,
            models.ChatMessage.is_active == True
        ).all()
        
        assert len(msgs_a) == 1, f"期望新会话只有1条消息，实际有 {len(msgs_a)} 条"
        cloned_msg = msgs_a[0]
        assert cloned_msg.role == msg2.role, "角色不匹配"
        assert cloned_msg.content == msg2.content, "内容不匹配"
        assert cloned_msg.emotion_tag == msg2.emotion_tag, "情绪不匹配"
        assert cloned_msg.affection_change == msg2.affection_change, "好感度变化不匹配"
        assert cloned_msg.id != msg2.id, "消息ID不能相同（应当为复制的新行）"
        assert cloned_msg.parent_id is None, "分支首条消息 parent_id 应当为 None"
        print(f"[SUCCESS] 场景 A 校验通过！新消息已成功复制并绑定至新分支 {branch_a_id}")

        # 6. 测试场景 B：未指定 start_message_id，退避到父会话最后一条 active 消息 (即 msg3)
        print("\n--- 测试场景 B: 未指定消息分叉 (退避至最后一条) ---")
        req_branch_b = SessionCreate(
            character_id=char.id,
            parent_session_id=parent_session_id,
            title="分支 B"
        )
        res_branch_b = create_session(req_branch_b, db)
        branch_b_id = res_branch_b["session_id"]

        # 验证分支 B 的消息
        msgs_b = db.query(models.ChatMessage).filter(
            models.ChatMessage.session_id == branch_b_id,
            models.ChatMessage.is_active == True
        ).all()

        assert len(msgs_b) == 1, f"期望新会话只有1条消息，实际有 {len(msgs_b)} 条"
        cloned_msg_b = msgs_b[0]
        assert cloned_msg_b.role == msg3.role, "角色不匹配"
        assert cloned_msg_b.content == msg3.content, "内容不匹配"
        assert cloned_msg_b.id != msg3.id, "消息ID不能相同"
        print(f"[SUCCESS] 场景 B 校验通过！新消息已成功退避复制并绑定至新分支 {branch_b_id}")

        # 7. 清理测试数据
        db.query(models.ChatMessage).filter(models.ChatMessage.session_id.in_([parent_session_id, branch_a_id, branch_b_id])).delete()
        db.query(models.SessionPersona).filter(models.SessionPersona.session_id.in_([parent_session_id, branch_a_id, branch_b_id])).delete()
        db.query(models.Session).filter(models.Session.id.in_([parent_session_id, branch_a_id, branch_b_id])).delete()
        db.query(models.Character).filter(models.Character.id == char.id).delete()
        db.commit()
        print("\n[SUCCESS] 测试数据已安全清理。")

    finally:
        db.close()

    print("==================================================")
    print(" 所有的单元测试均通过，符合预期！")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
