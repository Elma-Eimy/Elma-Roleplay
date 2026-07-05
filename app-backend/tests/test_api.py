"""
API 流程测试脚本 — 覆盖完整的 Session 对话流程

测试路径：
  创建角色 → 创建会话 → 对话 x2 → 获取历史 → 创建继承会话 → 继承对话 → 删除会话

用法：先启动 uvicorn main:app，然后运行 python test_api.py
"""

import os
import sys
from fastapi.testclient import TestClient

# Ensure root directory is in sys.path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from main import app

client = TestClient(app, raise_server_exceptions=False)


def make_request(endpoint, method="GET", payload=None):
    headers = {
        'X-API-Key': 'ILOVEYOU1234567890'
    }
    try:
        if method == "GET":
            response = client.get(endpoint, headers=headers)
        elif method == "POST":
            response = client.post(endpoint, json=payload, headers=headers)
        elif method == "PUT":
            response = client.put(endpoint, json=payload, headers=headers)
        elif method == "DELETE":
            response = client.delete(endpoint, headers=headers)
        else:
            return None, f"Unsupported method: {method}"
            
        try:
            return response.status_code, response.json()
        except Exception:
            return response.status_code, response.text
    except Exception as e:
        return None, str(e)


def run_tests():
    print("=" * 55)
    print("🚀 后端 API 流程测试 (Session 架构)")
    print("=" * 55)

    # ── 1. 创建角色 ──
    print("\n[测试 1] 创建角色 (/characters/create)")
    char_payload = {
        "name": "测试小助手",
        "description": "你是一个热心、活泼的AI小助手。你说话总是带着颜文字。",
        "personality": "开朗、热情、乐于助人",
        "first_mes": "你好呀！(≧▽≦) 有什么我可以帮你的吗？",
        "system_prompt_override": "你是一个活泼可爱的AI助手，每句话结尾尽量使用颜文字。",
    }
    status, response = make_request("/characters/create", "POST", char_payload)
    if status == 200:
        print(f"  ✅ 成功! {response}")
        char_id = response.get("character_id")
    else:
        print(f"  ❌ 失败 ({status}): {response}")
        return

    # ── 2. 获取角色列表 ──
    print("\n[测试 2] 获取角色列表 (/characters)")
    status, response = make_request("/characters", "GET")
    if status == 200:
        chars = response.get("characters", [])
        print(f"  ✅ 成功! 共 {len(chars)} 个角色")
        for c in chars:
            print(f"     - [{c['id']}] {c['name']}")
    else:
        print(f"  ❌ 失败 ({status}): {response}")

    # ── 3. 创建会话 ──
    print("\n[测试 3] 创建会话 (/sessions/create)")
    session_payload = {
        "character_id": char_id,
        "title": "测试对话 1",
    }
    status, response = make_request("/sessions/create", "POST", session_payload)
    if status == 200:
        print(f"  ✅ 成功! {response}")
        session_id = response.get("session_id")
    else:
        print(f"  ❌ 失败 ({status}): {response}")
        return

    # ── 4. 对话回合 1 ──
    print("\n[测试 4] 对话回合 1 (/chat)")
    chat_payload = {
        "session_id": session_id,
        "user_message": "你好！你能帮我写一段Python的print代码吗？",
    }
    print(f"  发送: {chat_payload['user_message']}")
    status, response = make_request("/chat", "POST", chat_payload)
    if status == 200:
        print(f"  ✅ AI: {response.get('reply')}")
        print(f"     (好感: {response.get('affection_change'):+d}, 情绪: {response.get('emotion_tag')}, 总好感: {response.get('affection_score')})")
    else:
        print(f"  ❌ 失败 ({status}): {response}")

    # ── 5. 对话回合 2（验证上下文） ──
    print("\n[测试 5] 对话回合 2 (/chat)")
    chat_payload2 = {
        "session_id": session_id,
        "user_message": "把它改成打印 'Hello World' 呢？",
    }
    print(f"  发送: {chat_payload2['user_message']}")
    status, response = make_request("/chat", "POST", chat_payload2)
    if status == 200:
        print(f"  ✅ AI: {response.get('reply')}")
    else:
        print(f"  ❌ 失败 ({status}): {response}")

    # ── 6. 获取聊天历史 ──
    print(f"\n[测试 6] 获取聊天历史 (/sessions/{session_id}/history)")
    status, response = make_request(f"/sessions/{session_id}/history", "GET")
    if status == 200:
        msgs = response.get("messages", [])
        print(f"  ✅ 共 {len(msgs)} 条消息")
        for m in msgs:
            preview = m['content'][:40] + "..." if len(m['content']) > 40 else m['content']
            print(f"     [{m['role']}] {preview}")
    else:
        print(f"  ❌ 失败 ({status}): {response}")

    # ── 7. 获取会话详情 ──
    print(f"\n[测试 7] 获取会话详情 (/sessions/{session_id})")
    status, response = make_request(f"/sessions/{session_id}", "GET")
    if status == 200:
        persona = response.get("persona", {})
        print(f"  ✅ 标题: {response.get('title')}")
        print(f"     好感度: {persona.get('affection_score')}, 心情: {persona.get('current_mood')}")
    else:
        print(f"  ❌ 失败 ({status}): {response}")

    # ── 8. 创建继承会话 ──
    print("\n[测试 8] 创建继承会话 (/sessions/create with parent)")
    inherit_payload = {
        "character_id": char_id,
        "parent_session_id": session_id,
        "title": "继承对话",
    }
    status, response = make_request("/sessions/create", "POST", inherit_payload)
    if status == 200:
        print(f"  ✅ 成功! inherited={response.get('inherited')}, session_id={response.get('session_id')}")
        child_session_id = response.get("session_id")
    else:
        print(f"  ❌ 失败 ({status}): {response}")
        child_session_id = None

    # ── 9. 在继承会话中对话 ──
    if child_session_id:
        print("\n[测试 9] 继承会话中对话 (/chat)")
        chat_payload3 = {
            "session_id": child_session_id,
            "user_message": "你还记得我之前让你写的代码吗？",
        }
        print(f"  发送: {chat_payload3['user_message']}")
        status, response = make_request("/chat", "POST", chat_payload3)
        if status == 200:
            print(f"  ✅ AI: {response.get('reply')}")
            print(f"     (总好感: {response.get('affection_score')})")
        else:
            print(f"  ❌ 失败 ({status}): {response}")

    # ── 10. 获取会话列表 ──
    print(f"\n[测试 10] 获取会话列表 (/sessions?character_id={char_id})")
    status, response = make_request(f"/sessions?character_id={char_id}", "GET")
    if status == 200:
        sessions = response.get("sessions", [])
        print(f"  ✅ 共 {len(sessions)} 个会话")
        for s in sessions:
            parent = f" ← 继承自 #{s.get('parent_session_id')}" if s.get('parent_session_id') else ""
            print(f"     [{s['id']}] {s['title']}{parent}")
    else:
        print(f"  ❌ 失败 ({status}): {response}")
    # ── 10.5 验证会话分页与角色分页 (分页新功能测试) ──
    print(f"\n[测试 10.5] 测试会话与角色分页")
    status, response = make_request("/characters?limit=1", "GET")
    if status == 200:
        chars = response.get("characters", [])
        print(f"  ✅ 成功拉取1个角色 (Limit=1), 实际拉取数量: {len(chars)}")
    else:
        print(f"  ❌ 角色分页测试失败 ({status}): {response}")

    status, response = make_request(f"/sessions?character_id={char_id}&limit=1", "GET")
    if status == 200:
        sessions = response.get("sessions", [])
        print(f"  ✅ 成功拉取1个会话 (Limit=1), 实际拉取数量: {len(sessions)}")
    else:
        print(f"  ❌ 会话分页测试失败 ({status}): {response}")
    # ── 11. 安全删除父会话（测试继承链重连） ──
    print(f"\n[测试 11] 安全删除父会话 (DELETE /sessions/{session_id})")
    status, response = make_request(f"/sessions/{session_id}", "DELETE")
    if status == 200:
        print(f"  ✅ 成功! {response}")
    else:
        print(f"  ❌ 失败 ({status}): {response}")

    print("\n" + "=" * 55)
    print("🎉 自动化测试脚本执行完毕")
    print("=" * 55)


if __name__ == "__main__":
    run_tests()
