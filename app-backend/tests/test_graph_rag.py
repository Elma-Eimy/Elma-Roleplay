"""
知识图谱 RAG (Graph RAG) 单元测试脚本

测试内容：
  1. 实体与关系的 Upsert（去重与更新）
  2. 实体匹配与 1-hop / 2-hop 关系检索
  3. 继承链（SessionPersona.parent_persona_id）跨代际知识图谱查询与继承
  4. 提示词格式化输出校验
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
from core.models import Character, Session, SessionPersona, GraphEntity, GraphRelation
from services.graph_service import upsert_graph_data, retrieve_graph_context

def run_graph_rag_test():
    print("=" * 60)
    print("🚀 开始运行知识图谱 Graph RAG 单元测试...")
    print("=" * 60)

    # 1. 初始化表
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    try:
        # 2. 构造测试数据
        print("\n[Step 1] 构造测试角色与继承会话树...")
        character = Character(
            name="图谱测试姬",
            description="用于测试知识图谱检索的测试助理。",
            first_mes="你好！"
        )
        db.add(character)
        db.flush()

        # 父代 Session/Persona
        session_parent = Session(title="父代故事线")
        db.add(session_parent)
        db.flush()

        persona_parent = SessionPersona(
            session_id=session_parent.id,
            character_id=character.id,
            affection_score=50,
            current_mood="平静"
        )
        db.add(persona_parent)
        db.flush()

        # 子代 Session/Persona（模拟剧情分叉继承）
        session_child = Session(
            parent_session_id=session_parent.id,
            title="子代分叉线"
        )
        db.add(session_child)
        db.flush()

        persona_child = SessionPersona(
            session_id=session_child.id,
            character_id=character.id,
            parent_persona_id=persona_parent.id,
            affection_score=60,
            current_mood="开心"
        )
        db.add(persona_child)
        db.flush()

        # 3. 测试父代图谱 Upsert
        print("\n[Step 2] 测试父代图谱数据 Upsert...")
        parent_entities = [
            {"name": "小红", "entity_type": "person", "description": "用户的初中同学。"},
            {"name": "草莓蛋糕", "entity_type": "object", "description": "一种非常甜的甜品。"}
        ]
        parent_relations = [
            {"source": "小红", "relation_type": "likes", "target": "草莓蛋糕", "description": "小红非常喜欢吃草莓蛋糕。", "importance": 0.8},
            {"source": "用户", "relation_type": "friend", "target": "小红", "description": "用户和小红是好朋友。", "importance": 0.9}
        ]

        upsert_graph_data(
            persona_id=persona_parent.id,
            entities=parent_entities,
            relations=parent_relations,
            db=db
        )
        db.commit()

        # 验证写入
        db_entities = db.query(GraphEntity).filter(GraphEntity.persona_id == persona_parent.id).all()
        db_relations = db.query(GraphRelation).filter(GraphRelation.persona_id == persona_parent.id).all()
        print(f"  - 父代写入实体数: {len(db_entities)} (预期: 3, 自动包含'用户')")
        print(f"  - 父代写入关系数: {len(db_relations)} (预期: 2)")
        assert len(db_relations) == 2, "父代关系数不匹配"

        # 4. 测试子代图谱增量写入与继承关系检索
        print("\n[Step 3] 测试子代图谱数据 Upsert (增加新实体'Alice'并更新'小红'的关系)...")
        # 子代增加了新人物 Alice，以及用户跟 Alice 的关系
        child_entities = [
            {"name": "Alice", "entity_type": "person", "description": "用户的大学室友。"},
            {"name": "小红", "entity_type": "person", "description": "用户高中最要好的发小。"} # 更新描述
        ]
        child_relations = [
            {"source": "用户", "relation_type": "friend", "target": "Alice", "description": "用户和 Alice 是好朋友。", "importance": 0.75},
            {"source": "小红", "relation_type": "classmate", "target": "Alice", "description": "小红和 Alice 是大学同班同学。", "importance": 0.6}
        ]

        upsert_graph_data(
            persona_id=persona_child.id,
            entities=child_entities,
            relations=child_relations,
            db=db
        )
        db.commit()

        # 5. 测试检索功能 (三项核心检索场景)
        print("\n[Step 4] 运行 Graph RAG 检索校验...")

        # 场景 A: 匹配子代新实体 "Alice"
        print("\n  >> 场景 A: 查询中提到 'Alice'")
        context_a = retrieve_graph_context(
            persona_id=persona_child.id,
            query_text="今天 Alice 来找我玩了。",
            db=db
        )
        print("  - 检索上下文输出:\n" + context_a)
        assert "Alice" in context_a
        assert "大学室友" in context_a
        assert "用户和 Alice 是好朋友" in context_a

        # 场景 B: 跨代际检索继承
        # 在子 Session 查询 "小红" 与 "草莓蛋糕"（这俩在子 Session 没建立直接关系，是从父代继承的）
        print("\n  >> 场景 B: 子代查询继承关系 '小红'")
        context_b = retrieve_graph_context(
            persona_id=persona_child.id,
            query_text="我今天见到小红了，她看起来很开心。",
            db=db
        )
        print("  - 检索上下文输出:\n" + context_b)
        assert "小红" in context_b
        # 描述应该是子代覆盖后的新描述 "高中最要好的发小"
        assert "高中最要好的发小" in context_b
        # 应该召回父代继承的 likes 蛋糕关系 (1-hop)
        assert "小红非常喜欢吃草莓蛋糕" in context_b

        # 场景 C: 二度二环关联 (2-hop)
        # 用户只提到了 "小红"，但由于 Alice 与小红是同学，且用户和 Alice 也是朋友，
        # 应召回小红、Alice、用户三者之间的复杂三角网络。
        print("\n  >> 场景 C: 二度网络匹配（提及'小红'，关联出邻居'Alice'）")
        context_c = retrieve_graph_context(
            persona_id=persona_child.id,
            query_text="我跟小红聊天呢。",
            db=db
        )
        print("  - 检索上下文输出:\n" + context_c)
        # 应该包含 Alice 的定义及小红与 Alice 的同学关系
        assert "Alice" in context_c
        assert "小红和 Alice 是大学同班同学" in context_c

        print("\n" + "=" * 60)
        print("🎉 恭喜！所有知识图谱检索单元测试均通过！")
        print("=" * 60)

    except Exception as e:
        db.rollback()
        print(f"\n❌ 测试失败，抛出异常: {e}")
        import traceback
        traceback.print_exc()
        raise e
    finally:
        # 清理测试垃圾数据
        print("\n[Step 5] 清理单元测试产生的数据库脏数据...")
        try:
            db.query(GraphRelation).filter(GraphRelation.persona_id.in_([persona_parent.id, persona_child.id])).delete(synchronize_session=False)
            db.query(GraphEntity).filter(GraphEntity.persona_id.in_([persona_parent.id, persona_child.id])).delete(synchronize_session=False)
            db.delete(persona_child)
            db.delete(persona_parent)
            db.delete(session_child)
            db.delete(session_parent)
            db.delete(character)
            db.commit()
            print("  ✅ 数据库清理干净！")
        except Exception as err:
            db.rollback()
            print(f"  ❌ 清理失败: {err}")
        db.close()

if __name__ == "__main__":
    run_graph_rag_test()
