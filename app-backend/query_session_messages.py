"""
获取特定会话的历史消息诊断脚本。
用法：python query_session_messages.py <会话ID> [数量, 默认15]
"""
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.database import SessionLocal
from core import models

def query_session_messages(session_id: int, limit: int = 15):
    db = SessionLocal()
    print(f"\n📊 正在查询 会话#{session_id} 的最近 {limit} 条历史消息：")
    print("=" * 70)
    
    # 查找会话是否存在
    session = db.query(models.Session).filter(models.Session.id == session_id).first()
    if not session:
        print(f"❌ 找不到 ID 为 {session_id} 的会话！")
        db.close()
        return

    print(f"会话 ID: {session.id} | 会话标题: {session.title}")
    
    # 查询该会话最近的历史消息 (获取最近 limit 条，按 ID 倒序)
    messages = (
        db.query(models.ChatMessage)
        .filter(models.ChatMessage.session_id == session_id)
        .order_by(models.ChatMessage.id.desc())
        .limit(limit)
        .all()
    )
    
    # 反转回时间正序输出
    messages.reverse()
    
    if not messages:
        print("  当前会话没有检测到任何消息记录。")
    else:
        for idx, m in enumerate(messages):
            role_str = m.role.value.upper()
            active_str = "✔️ [有效]" if m.is_active else "❌ [失效/候选]"
            emotion_str = f" | 情绪: {m.emotion_tag}" if m.emotion_tag else ""
            affection_str = f" | 好感变动: {m.affection_change:+d}" if m.affection_change is not None else ""
            parent_str = f" | 父ID: {m.parent_id}" if m.parent_id else ""
            
            print(f"\n[{idx+1}] 消息ID: {m.id} | 角色: {role_str} | 状态: {active_str}{parent_str}{emotion_str}{affection_str}")
            print(f"创建时间: {m.created_at}")
            print(f"消息内容: {m.content}")
            print("-" * 50)
            
    db.close()

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python query_session_messages.py <会话ID> [查询消息数量]")
        sys.exit(1)
        
    try:
        s_id = int(sys.argv[1])
        cnt = int(sys.argv[2]) if len(sys.argv) > 2 else 15
        query_session_messages(s_id, cnt)
    except ValueError:
        print("错误: 会话ID和消息数量参数必须是整数！")
        sys.exit(1)
