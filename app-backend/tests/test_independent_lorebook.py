import json
import os
import sys

# 将当前目录的父目录加入 python path以确保能正确引入 services 和 core
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SessionLocal, engine
from core import models
from core.models import Base
from services.lorebook.parse_lorebook import parse_sillytavern_lorebook
from services.lorebook.lorebook_engine import process_lorebook

def run_tests():
    print("==================================================")
    print(" 开始运行独立世界书库 (Independent Lorebook) 单元测试...")
    print("==================================================")
    
    # 1. 初始化数据库表 (会触发自动建表以生成 lorebooks & character_lorebooks 表)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    
    try:
        # 2. 清理可能存在的历史测试数据
        test_char_name = "测试法师角色"
        test_lb_name = "测试魔法世界设定集"
        
        db.query(models.Character).filter(models.Character.name == test_char_name).delete()
        db.query(models.Lorebook).filter(models.Lorebook.name == test_lb_name).delete()
        db.commit()
        
        # 3. 创建测试角色卡
        extensions_data = {
            "character_book": {
                "name": "测试角色自带书",
                "entries": [
                    {
                        "keys": ["法师"],
                        "content": "角色设定：法师擅长释放元素法术。",
                        "enabled": True,
                        "constant": False
                    }
                ]
            }
        }
        
        char = models.Character(
            name=test_char_name,
            description="一个测试用的法师人设。",
            first_mes="你好！",
            extensions=json.dumps(extensions_data, ensure_ascii=False)
        )
        db.add(char)
        db.commit()
        db.refresh(char)
        print(f"[SUCCESS] 创建测试角色成功: {char.name} (ID: {char.id})")
        
        # 4. 模拟 SillyTavern JSON 世界书导入
        st_lorebook_mock = {
            "name": test_lb_name,
            "description": "用于测试独立世界书库匹配机制的世界设定。",
            "scan_depth": 5,
            "token_budget": 2000,
            "recursive_scanning": True,
            "entries": {
                "0": {
                    "keys": ["冰霜术"],
                    "content": "设定：冰霜术能冻结水面和敌人。",
                    "enabled": True,
                    "constant": False,
                    "position": 1, # after_char
                    "priority": 50
                },
                "1": {
                    "keys": ["火球"],
                    "content": "常驻设定：火球能融化冰块。",
                    "enabled": True,
                    "constant": True, # 常驻触发
                    "position": 0, # before_char
                    "priority": 20
                }
            }
        }
        
        parsed_data = parse_sillytavern_lorebook(st_lorebook_mock)
        assert parsed_data["name"] == test_lb_name
        assert len(parsed_data["entries"]) == 2
        print("[SUCCESS] 成功解析 SillyTavern 格式 JSON 世界书数据")
        
        # 保存到数据库
        entries_str = json.dumps(parsed_data["entries"], ensure_ascii=False)
        lb = models.Lorebook(
            name=parsed_data["name"],
            description=parsed_data["description"],
            scan_depth=parsed_data["scan_depth"],
            token_budget=parsed_data["token_budget"],
            recursive_scanning=parsed_data["recursive_scanning"],
            entries=entries_str
        )
        db.add(lb)
        db.commit()
        db.refresh(lb)
        print(f"[SUCCESS] 导入独立世界书成功: {lb.name} (ID: {lb.id})")
        
        # 5. 绑定世界书到角色
        char.lorebooks.append(lb)
        db.commit()
        db.refresh(char)
        print(f"[SUCCESS] 成功将世界书 '{lb.name}' 关联绑定到角色 '{char.name}'")
        assert len(char.lorebooks) == 1
        assert char.lorebooks[0].id == lb.id
        
        # 6. 测试引擎词条检索合并激活 (process_lorebook)
        print("\n--- 启动检索扫描验证 ---")
        
        # 场景 A: 发送“火球”（包含独立书的常驻条目，不含关键字）
        result = process_lorebook(char, [], "你好！")
        before_contents = [e["content"] for e in result["before_char"]]
        after_contents = [e["content"] for e in result["after_char"]]
        
        # 独立书的常驻条目“火球”必须触发在 before_char 中
        assert any("融化冰块" in c for c in before_contents), "独立世界书的常驻触发失败"
        # 角色自带的“法师”条目不应触发
        assert not any("元素法术" in c for c in after_contents), "未命中关键字的专属条目错误触发"
        print("-> 场景 A (常驻触发) 验证成功！")
        
        # 场景 B: 发送“我是法师，用冰霜术”（同时命中角色专属词“法师”与绑定世界书词“冰霜术”）
        result = process_lorebook(char, [], "我是法师，我施展了冰霜术。")
        before_contents = [e["content"] for e in result["before_char"]]
        after_contents = [e["content"] for e in result["after_char"]]
        
        # 专属词触发
        assert any("元素法术" in c for c in after_contents), "角色卡专属词条触发失败"
        # 绑定词触发
        assert any("冻结水面" in c for c in after_contents), "关联绑定世界书的词条触发失败"
        print("-> 场景 B (专属+关联绑定合流触发) 验证成功！")
        
        # 7. 解除绑定测试
        char.lorebooks.remove(lb)
        db.commit()
        db.refresh(char)
        print("\n[SUCCESS] 成功解绑世界书与角色")
        assert len(char.lorebooks) == 0
        
        # 再次触发应不再包含独立书的内容
        result = process_lorebook(char, [], "我是法师，我施展了冰霜术。")
        after_contents = [e["content"] for e in result["after_char"]]
        assert any("元素法术" in c for c in after_contents)
        assert not any("冻结水面" in c for c in after_contents), "解绑后词条依然触发，解绑逻辑有误"
        print("-> 解绑后检索验证成功！")
        
        # 8. 测试级联清除：重新绑定并删除世界书
        char.lorebooks.append(lb)
        db.commit()
        db.refresh(char)
        assert len(char.lorebooks) == 1
        
        db.delete(lb)
        db.commit()
        db.refresh(char)
        print("[SUCCESS] 成功删除独立世界书")
        # 验证关联表中记录被 SQLite 自动级联清除，角色 lorebooks 清空
        assert len(char.lorebooks) == 0
        print("-> 级联删除验证成功！")
        
        # 清理角色记录
        db.delete(char)
        db.commit()
        print("[SUCCESS] 成功清理测试角色")
        
    except AssertionError as ae:
        print(f"\n[FAIL] 断言验证失败: {ae}")
        raise ae
    except Exception as e:
        print(f"\n[FAIL] 测试运行中触发未捕获异常: {e}")
        raise e
    finally:
        db.close()
        
    print("\n==================================================")
    print(" 独立世界书库所有单元测试全部通过！完美匹配设计预期。")
    print("==================================================")

if __name__ == "__main__":
    run_tests()
