"""
闭环记忆提纯与 RAG 检索测试脚本
"""

import urllib.request
import urllib.error
import json
import os
import sys

# 将当前目录的父目录加入 path，方便导入
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SessionLocal
from core.models import MemoryChunk, SessionPersona, Session
from services.memory_manager import get_character_collection, retrieve_memories

BASE_URL = "http://127.0.0.1:8000"
API_KEY = "ILOVEYOU1234567890"  # 对应 settings 中的开发 api key，若未开启 key 则直接传值


def make_request(endpoint, method="GET", payload=None):
    url = f"{BASE_URL}{endpoint}"
    headers = {
        'Content-Type': 'application/json',
        'X-API-Key': API_KEY
    }

    data = None
    if payload:
        data = json.dumps(payload).encode('utf-8')

    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req) as response:
            return response.status, json.loads(response.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode('utf-8')
    except urllib.error.URLError as e:
        return None, str(e.reason)


def run_closed_loop_test():
    print("=" * 70)
    print("🚀 闭环记忆提纯与 RAG 检索流程测试")
    print("=" * 70)

    # 1. 创建闭环测试专用角色
    print("\n[第一步] 创建专属测试角色 (/characters/create)")
    char_payload = {
        "name": "闭环测试助理",
        "description": "你是一个严谨且记性极好的测试助理。",
        "personality": "严谨、记性极好",
        "first_mes": "你好，我是测试助理，我会记住你告诉我的所有重要事情。",
        "system_prompt_override": "你是一个记性极佳的助理，回答时请简明扼要。",
    }
    status, response = make_request("/characters/create", "POST", char_payload)
    if status == 200:
        char_id = response.get("character_id")
        print(f"  ✅ 成功! 角色 ID: {char_id}")
    else:
        print(f"  ❌ 失败 ({status}): {response}")
        return

    # 2. 创建会话
    print("\n[第二步] 创建会话 (/sessions/create)")
    session_payload = {
        "character_id": char_id,
        "title": "闭环记忆测试会话",
    }
    status, response = make_request("/sessions/create", "POST", session_payload)
    if status == 200:
        session_id = response.get("session_id")
        persona_id = response.get("persona_id")
        print(f"  ✅ 成功! 会话 ID: {session_id}, Persona ID: {persona_id}")
    else:
        print(f"  ❌ 失败 ({status}): {response}")
        return

    # 3. 发送包含事实的对话，要求 AI 记忆
    print("\n[第三步] 发送包含具体事实的对话")
    chat_payload = {
        "session_id": session_id,
        "user_message": "你好！我叫小明，我最喜欢的食物是草莓蛋糕，你可要记住哦！",
    }
    print(f"  发送: {chat_payload['user_message']}")
    status, response = make_request("/chat", "POST", chat_payload)
    if status == 200:
        print(f"  ✅ AI 回复: {response.get('reply')}")
    else:
        print(f"  ❌ 失败 ({status}): {response}")
        return

    # 4. 手动触发记忆提纯
    print("\n[第四步] 触发记忆提纯流程 (/sessions/{id}/trigger_summary)")
    status, response = make_request(f"/sessions/{session_id}/trigger_summary", "POST")
    if status == 200:
        print(f"  ✅ 成功! 提纯完成，提取记忆条数: {response.get('extracted_count')}")
    else:
        print(f"  ❌ 失败 ({status}): {response}")
        return

    # 5. 直接查询 SQLite 数据库验证数据落地
    print("\n[第五步] 直接查询 SQLite 验证 MemoryChunk 存储")
    db = SessionLocal()
    try:
        chunks = db.query(MemoryChunk).filter(MemoryChunk.persona_id == persona_id).all()
        print(f"  📝 SQLite 中共找到 {len(chunks)} 条记忆分片:")
        for idx, chunk in enumerate(chunks, 1):
            print(f"     [{idx}] 类型: {chunk.memory_type.value} | 重要度: {chunk.importance_score} | 内容: {chunk.content}")
        
        assert len(chunks) > 0, "❌ 测试失败: SQLite 中没有找到任何提取出的记忆分片！"
        print("  ✅ SQLite 验证通过！")
    finally:
        db.close()

    # 6. 直接查询 ChromaDB 向量数据库验证数据落地
    print("\n[第六步] 直接查询 ChromaDB 验证向量存储")
    try:
        collection = get_character_collection(char_id)
        existing = collection.get(where={"persona_id": persona_id}, include=["embeddings", "documents"])
        ids = existing.get("ids", [])
        docs = existing.get("documents", [])
        print(f"  🎨 ChromaDB 中共找到 {len(ids)} 个向量文档:")
        for idx, doc in enumerate(docs, 1):
            print(f"     [{idx}] 内容: {doc}")
            
        assert len(ids) > 0, "❌ 测试失败: ChromaDB 中没有查到任何对应的向量数据！"
        print("  ✅ ChromaDB 验证通过！")
    except Exception as e:
        print(f"  ❌ ChromaDB 查询失败: {e}")
        return

    # 7. 调用 retrieve_memories 并打印打分明细，验证 RAG 算法
    print("\n[第七步] 运行内部 RAG 检索并打印复合打分明细")
    db = SessionLocal()
    try:
        recalled = retrieve_memories(
            persona_id=persona_id,
            character_id=char_id,
            query="我最喜欢的食物是什么？",
            db=db,
            top_k=3
        )
        print(f"  🔍 查询词: '我最喜欢的食物是什么？'，检索结果如下:")
        for idx, mem in enumerate(recalled, 1):
            print(f"     [{idx}] 相似度得分: {mem['sim_score']:.4f} | 重要性得分: {mem['importance_score']:.4f} | 衰减得分: {mem['time_score']:.4f} | 综合最终得分: {mem['final_score']:.4f}")
            print(f"         内容: {mem['content']}")
            
        assert len(recalled) > 0, "❌ 测试失败: RAG 未检索到任何记忆！"
        print("  ✅ 检索打分算法执行通过！")
    finally:
        db.close()

    # 8. 闭环测试验证：向 AI 询问之前告知的事实，看其是否正确检索回答
    print("\n[第八步] 闭环问答：向 AI 提问以验证 RAG 效果")
    ask_payload = {
        "session_id": session_id,
        "user_message": "你还记得我叫什么名字，以及我最喜欢吃什么食物吗？",
    }
    print(f"  发送: {ask_payload['user_message']}")
    status, response = make_request("/chat", "POST", ask_payload)
    if status == 200:
        reply = response.get('reply', '')
        print(f"  ✅ AI 回答: {reply}")
        # 验证大模型回复中是否包含了记忆内容
        has_name = "小明" in reply
        has_food = "草莓" in reply or "蛋糕" in reply
        
        print(f"  ⭐ 验证回复中是否含有关键字 '小明': {'通过' if has_name else '未检测到'}")
        print(f"  ⭐ 验证回复中是否含有关键字 '草莓/蛋糕': {'通过' if has_food else '未检测到'}")
        
        if has_name and has_food:
            print("\n🎉🎉 恭喜！闭环记忆写入与 RAG 检索验证完全成功！ 🎉🎉")
        else:
            print("\n⚠️ 闭环问答未完全通过，大模型回答中没有包含完整的记忆细节（可能大模型没有理解提取出的事实）。")
    else:
        print(f"  ❌ 失败 ({status}): {response}")

    # 清理测试数据
    print(f"\n[第九步] 清理测试会话与角色")
    status, response = make_request(f"/sessions/{session_id}", "DELETE")
    if status == 200:
        print(f"  ✅ 成功删除测试会话: {response}")
    else:
        print(f"  ❌ 删除测试会话失败: {response}")


if __name__ == "__main__":
    run_closed_loop_test()
