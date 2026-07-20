import json
import os
import sys

# 将当前目录的父目录加入 python path 以确保能正确引入 services 和 core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from services.lorebook.lorebook_engine import process_lorebook

# 模拟 Character 数据库 ORM 对象
class MockCharacter:
    def __init__(self, extensions_data):
        self.id = 999
        self.extensions = json.dumps(extensions_data, ensure_ascii=False)


def run_tests():
    print("==================================================")
    print(" 开始运行世界书 (Lorebook) 引擎单元测试...")
    print("==================================================")
    
    from core.config import settings
    # 显式关闭向量语义检索以运行传统关键词匹配单元测试
    settings.APP_LOREBOOK_SEMANTIC_ENABLED = False

    # 1. 基础配置：模拟含有世界书数据的角色卡扩展字段
    extensions_data = {
        "character_book": {
            "name": "魔法学院世界书",
            "scan_depth": 3,
            "token_budget": 1000,
            "recursive_scanning": True,
            "entries": [
                {
                    "keys": ["学院", "学院历史"],
                    "content": "设定背景：霍格魔法学院成立于1000年前，是世界上最伟大的魔法学府。",
                    "enabled": True,
                    "constant": False,
                    "case_sensitive": False,
                    "selective": False,
                    "position": "before_char",
                    "insertion_order": 1
                },
                {
                    "keys": ["禁林"],
                    "content": "警告：后方的禁林里居住着凶猛的魔法生物，学生禁止入内。",
                    "enabled": True,
                    "constant": True, # 常驻触发
                    "position": "before_char",
                    "insertion_order": 2
                },
                {
                    "keys": ["火球术", "火焰"],
                    "content": "法术设定：火球术是一种初级元素法术，需要配合法杖施展。",
                    "enabled": True,
                    "constant": False,
                    "case_sensitive": False,
                    "selective": True, # 选择性触发，需要 secondary_keys
                    "secondary_keys": ["法师", "巫师"],
                    "position": "after_char",
                    "insertion_order": 10
                },
                {
                    "keys": ["Mana"],
                    "content": "能量规则：Mana（魔力）是释放一切法术的核心源泉。",
                    "enabled": True,
                    "constant": False,
                    "case_sensitive": True, # 大小写敏感
                    "position": "after_char",
                    "insertion_order": 20
                },
                {
                    "keys": ["召唤", "召唤术"],
                    "content": "召唤法术可以召唤出【元素生物】协助战斗。",
                    "enabled": True,
                    "constant": False,
                    "position": "after_char",
                    "insertion_order": 30
                },
                {
                    "keys": ["元素生物"],
                    "content": "元素设定：元素生物对普通物理攻击完全免疫。",
                    "enabled": True,
                    "constant": False,
                    "position": "after_char",
                    "insertion_order": 40
                },
                {
                    "keys": ["超限"],
                    "content": "X" * 1500, # 用于测试超出预算
                    "enabled": True,
                    "constant": False,
                    "position": "after_char",
                    "insertion_order": 50
                }
            ]
        }
    }

    char = MockCharacter(extensions_data)

    # ──────────────────────────────────────────────────
    # 测试案例 1：常驻触发与匹配深度限制
    # ──────────────────────────────────────────────────
    print("\n[测试 1] 验证 constant（常驻）触发与扫描深度限制...")
    recent_history = [
        {"role": "user", "content": "我们今天去学院看看吧？"}, # 距离 4
        {"role": "assistant", "content": "好的。"},             # 距离 3
        {"role": "user", "content": "今天天气真好。"},          # 距离 2
        {"role": "assistant", "content": "确实挺不错的。"}      # 距离 1
    ]
    user_msg = "我们走吧。" # 当前输入
    
    # 扫描深度为 3，历史里只看 3、2、1，因此 "学院"（距离 4）不应该触发
    result = process_lorebook(char, recent_history, user_msg)
    
    # 验证 "禁林" (constant) 一定触发，且在 before_char 中
    before_contents = [e["content"] for e in result["before_char"]]
    assert any("警告：后方的禁林" in c for c in before_contents), "常驻触发失败"
    
    # 验证 "学院" 因超出深度没有触发
    assert not any("霍格魔法学院成立于1000年前" in c for c in before_contents), "扫描深度控制失效，触发了过早的历史"
    print("-> [测试 1] 通过！")

    # ──────────────────────────────────────────────────
    # 测试案例 2：关键字正常触发
    # ──────────────────────────────────────────────────
    print("\n[测试 2] 验证普通关键字匹配触发...")
    recent_history = [
        {"role": "user", "content": "我们今天去学院看看吧？"} # 这一次在扫描深度内 (深度为 3，历史只有这 1 条)
    ]
    user_msg = "走吧！"
    result = process_lorebook(char, recent_history, user_msg)
    
    before_contents = [e["content"] for e in result["before_char"]]
    assert any("霍格魔法学院成立于1000年前" in c for c in before_contents), "关键字触发失败"
    print("-> [测试 2] 通过！")

    # ──────────────────────────────────────────────────
    # 测试案例 3：选择性双重触发（selective & secondary_keys）
    # ──────────────────────────────────────────────────
    print("\n[测试 3] 验证 selective (选择性触发) 条件匹配...")
    # 只包含 keys ("火球术")，不包含 secondary_keys ("法师"/"巫师")
    recent_history = []
    user_msg = "我会用火球术。"
    result = process_lorebook(char, recent_history, user_msg)
    after_contents = [e["content"] for e in result["after_char"]]
    assert not any("法术设定：火球术" in c for c in after_contents), "只包含主关键字时不应触发选择性条目"

    # 同时包含 keys ("火球术") 与 secondary_keys ("巫师")
    user_msg = "我是一名巫师，正在施展火球术。"
    result = process_lorebook(char, recent_history, user_msg)
    after_contents = [e["content"] for e in result["after_char"]]
    assert any("法术设定：火球术" in c for c in after_contents), "同时包含主副关键字时应正确触发选择性条目"
    print("-> [测试 3] 通过！")

    # ──────────────────────────────────────────────────
    # 测试案例 4：大小写敏感控制
    # ──────────────────────────────────────────────────
    print("\n[测试 4] 验证 case_sensitive 大小写敏感性...")
    # 小写的 "mana" 应不触发大小写敏感的 "Mana"
    user_msg = "我的 mana 耗尽了。"
    result = process_lorebook(char, recent_history, user_msg)
    after_contents = [e["content"] for e in result["after_char"]]
    assert not any("能量规则：Mana（魔力）" in c for c in after_contents), "大小写敏感失效：小写触发了大写条目"

    # 大写的 "Mana" 应正确触发
    user_msg = "我的 Mana 耗尽了。"
    result = process_lorebook(char, recent_history, user_msg)
    after_contents = [e["content"] for e in result["after_char"]]
    assert any("能量规则：Mana（魔力）" in c for c in after_contents), "大小写敏感失效：大写未能触发条目"
    print("-> [测试 4] 通过！")

    # ──────────────────────────────────────────────────
    # 测试案例 5：递归扫描激活（recursive_scanning）
    # ──────────────────────────────────────────────────
    print("\n[测试 5] 验证 recursive_scanning 递归扫描触发...")
    # 用户输入只提及 "召唤"，触发 召唤 条目。
    # 召唤条目内容含 "元素生物"，触发 元素生物 条目。
    user_msg = "我要施展召唤术。"
    result = process_lorebook(char, recent_history, user_msg)
    after_contents = [e["content"] for e in result["after_char"]]
    assert any("召唤法术可以召唤出【元素生物】" in c for c in after_contents), "一级触发失败"
    assert any("元素设定：元素生物对普通物理攻击" in c for c in after_contents), "二级递归触发失败"
    print("-> [测试 5] 通过！")

    # ──────────────────────────────────────────────────
    # 测试案例 6：Token 预算控制（token_budget）
    # ──────────────────────────────────────────────────
    print("\n[测试 6] 验证 token_budget 预算截断控制...")
    # 触发 "超限" 动作（其内容长达 1500 字符，超出了 1000 的预算）
    user_msg = "超限"
    result = process_lorebook(char, recent_history, user_msg)
    after_contents = [e["content"] for e in result["after_char"]]
    # 验证 "超限" 被拦截，而其他较短的常驻条目（如禁林）依然存在
    assert not any("X" * 1500 in c for c in after_contents), "Token 预算控制失效，超限内容被注入"
    
    before_contents = [e["content"] for e in result["before_char"]]
    assert any("警告：后方的禁林" in c for c in before_contents), "预算控制过滤了其他合法小条目"
    print("-> [测试 6] 通过！")

    # ──────────────────────────────────────────────────
    # 测试案例 7：验证向量语义触发接口兼容性与稳定性（不崩溃）
    # ──────────────────────────────────────────────────
    print("\n[测试 7] 验证向量语义检索启动与容错兼容性...")
    settings.APP_LOREBOOK_SEMANTIC_ENABLED = True
    try:
        # 触发向量语义检索，即使网络异常导致 API 失败，也应当能通过 try-except 容错处理
        result = process_lorebook(char, recent_history, "火焰法术")
        print("-> [测试 7] 通过！")
    except Exception as e:
        assert False, f"向量语义检索触发了未捕获的崩溃异常: {e}"
    finally:
        settings.APP_LOREBOOK_SEMANTIC_ENABLED = False

    # ──────────────────────────────────────────────────
    # 测试清理：删除临时的 ChromaDB collection
    # ──────────────────────────────────────────────────
    try:
        from services.infrastructure.clients import chroma_client
        chroma_client.delete_collection("lorebook_999")
        print("[INFO] 成功清理测试向量集合: lorebook_999")
    except Exception as e:
        print(f"[WARN] 清理测试向量集合失败: {e}")

    print("\n==================================================")
    print(" 所有世界书单元测试全部通过！结果完美匹配设计预期。")
    print("==================================================")


if __name__ == "__main__":
    run_tests()
