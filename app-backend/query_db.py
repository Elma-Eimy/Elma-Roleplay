"""
数据库诊断脚本 — 查看 SQLite 和 ChromaDB 中的数据概览

用法：python query_db.py
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from core.database import SessionLocal
from core import models
import chromadb


def query_sqlite():
    db = SessionLocal()
    print("\n" + "=" * 50)
    print("📊 SQLite 数据库概览 (data.db)")
    print("=" * 50)

    # ── 角色 ──
    characters = db.query(models.Character).all()
    print(f"\n🎭 角色 ({len(characters)} 个):")
    for c in characters:
        desc = (c.description[:30] + "...") if c.description and len(c.description) > 30 else (c.description or "")
        print(f"  [{c.id}] {c.name:<12} | {desc}")

    # ── 会话 ──
    sessions = db.query(models.Session).all()
    print(f"\n📝 会话 ({len(sessions)} 个):")
    for s in sessions:
        persona = s.persona
        char_name = persona.character.name if persona and persona.character else "?"
        parent = f" ← 继承自 #{s.parent_session_id}" if s.parent_session_id else ""
        mood = persona.current_mood if persona else ""
        affection = persona.affection_score if persona else 0
        print(f"  [{s.id}] \"{s.title}\" | 角色: {char_name} | 好感: {affection} | 心情: {mood}{parent}")

    # ── 最近消息 ──
    print(f"\n💬 最近 10 条消息:")
    messages = (
        db.query(models.ChatMessage)
        .order_by(models.ChatMessage.created_at.desc())
        .limit(10)
        .all()
    )
    if not messages:
        print("  无记录。")
    for m in messages:
        content = (m.content[:40].replace('\n', ' ') + "...") if len(m.content) > 40 else m.content.replace('\n', ' ')
        emotion = f" [{m.emotion_tag}]" if m.emotion_tag else ""
        print(f"  [会话#{m.session_id}] {m.role.value.upper():<9}{emotion} | {content}")

    # ── 记忆片段 ──
    chunk_count = db.query(models.MemoryChunk).count()
    print(f"\n🧩 记忆片段: 共 {chunk_count} 条")
    if chunk_count > 0:
        recent_chunks = (
            db.query(models.MemoryChunk)
            .order_by(models.MemoryChunk.created_at.desc())
            .limit(5)
            .all()
        )
        for mc in recent_chunks:
            content = (mc.content[:40].replace('\n', ' ') + "...") if len(mc.content) > 40 else mc.content.replace('\n', ' ')
            print(f"  [Persona#{mc.persona_id}] {mc.memory_type.value:<12} | 重要性: {mc.importance_score:.1f} | {content}")

    db.close()


def query_chroma():
    print("\n" + "=" * 50)
    print("🧠 ChromaDB 向量记忆库概览 (chroma_data/)")
    print("=" * 50)

    chroma_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "chroma_data")
    if not os.path.exists(chroma_path):
        print("ChromaDB 目录不存在，暂无记忆数据。")
        return

    try:
        client = chromadb.PersistentClient(path=chroma_path)
        collections = client.list_collections()
        if not collections:
            print("当前没有任何记忆集合 (Collections)。")
            return

        for col in collections:
            count = col.count()
            print(f"\n📂 集合: {col.name} ({count} 条记忆)")
            if count > 0:
                results = col.get(limit=3, include=["documents", "metadatas"])
                for i, (doc, meta) in enumerate(zip(results['documents'], results['metadatas'])):
                    doc_preview = (doc[:50].replace('\n', ' ') + "...") if len(doc) > 50 else doc.replace('\n', ' ')
                    persona_id = meta.get('persona_id', '?')
                    mem_type = meta.get('memory_type', '?')
                    importance = meta.get('importance_score', 0)
                    print(f"   [{i+1}] Persona#{persona_id} | {mem_type} | 重要性: {importance:.1f} | {doc_preview}")
    except Exception as e:
        print(f"无法读取 ChromaDB 数据，可能被服务器占用。错误: {e}")


if __name__ == "__main__":
    query_sqlite()
    query_chroma()
    print("\n查询完毕。")
