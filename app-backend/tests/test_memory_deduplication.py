"""
Memory deduplication and fork-inheritance integration tests.

Scenarios:
  1. Main flow: parent-child replacement + retrieval masking
  2. Relationship classifier LLM-failure fallback
  3. Three-level fork inheritance
"""

import os
import sys
from unittest.mock import patch, MagicMock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.database import SessionLocal
from core.models import (
    MemoryChunk, MemoryType, SessionPersona,
    Session, Character, ChatMessage, MessageRole,
)
from services.memory.memory_manager import (
    retrieve_memories, add_memory_chunk, delete_persona_memories,
)
from services.memory.memory_extraction_service import (
    summarize_and_store_memory,
    resolve_memory_relationship_via_llm,
)


def test_relationship_classifier_fallback():
    """When LLM call raises, relationship resolution must preserve both cards."""
    print("\n[Test 1] relationship classifier LLM-failure fallback")
    old = "User likes strawberry cake."
    new = "User likes strawberry cake, especially with hot milk."
    with patch("services.memory.memory_extraction_service.get_llm_provider") as mock_get_provider:
        mock_provider = MagicMock()
        mock_provider.generate.side_effect = ConnectionError("mock")
        mock_get_provider.return_value = mock_provider
        result = resolve_memory_relationship_via_llm(old, new)
    assert result == {"relation": "coexist", "resolved_content": new}, \
        f"Fallback failed: got {result!r}"
    print(f"   [PASS] fallback OK -> {result!r}")


def test_multi_level_fork_cow():
    """Child sees grandparent memory through 2 inheritance levels; gp is read-only."""
    print("\n[Test 2] Three-level fork COW")
    db = SessionLocal()
    char = Character(name="MultiLevelTest", description="t", personality="t", first_mes="hi")
    db.add(char); db.commit(); db.refresh(char)
    char_id = char.id

    try:
        from services.infrastructure.clients import chroma_client
        chroma_client.delete_collection(name=f"character_{char_id}")
    except Exception:
        pass

    gp_sess = p_sess = c_sess = None
    gp_persona = p_persona = c_persona = None
    try:
        gp_sess = Session(title="gp")
        db.add(gp_sess); db.commit(); db.refresh(gp_sess)
        gp_persona = SessionPersona(session_id=gp_sess.id, character_id=char_id,
                                     current_mood="n", affection_score=0)
        db.add(gp_persona); db.commit(); db.refresh(gp_persona)

        gp_chunk = add_memory_chunk(
            persona_id=gp_persona.id, character_id=char_id,
            content="Xiao Ming likes strawberry cake.",
            memory_type=MemoryType.fact, importance_score=0.6,
            origin_session_id=gp_sess.id, source_message_id=None, db=db)
        orig = gp_chunk.content

        p_sess = Session(title="p", parent_session_id=gp_sess.id)
        db.add(p_sess); db.commit(); db.refresh(p_sess)
        p_persona = SessionPersona(session_id=p_sess.id, character_id=char_id,
                                    parent_persona_id=gp_persona.id,
                                    current_mood="n", affection_score=0)
        db.add(p_persona); db.commit(); db.refresh(p_persona)

        c_sess = Session(title="c", parent_session_id=p_sess.id)
        db.add(c_sess); db.commit(); db.refresh(c_sess)
        c_persona = SessionPersona(session_id=c_sess.id, character_id=char_id,
                                    parent_persona_id=p_persona.id,
                                    current_mood="n", affection_score=0)
        db.add(c_persona); db.commit(); db.refresh(c_persona)

        recalled = retrieve_memories(persona_id=c_persona.id, character_id=char_id,
                                      query="What does Xiao Ming like?",
                                      db=db, top_k=3, min_importance=0.0)
        print(f"   child recalled {len(recalled)} memories")
        assert any("strawberry" in m["content"].lower() for m in recalled), \
            "child must see grandparent memory through 2 levels"

        gp_after = db.query(MemoryChunk).filter(MemoryChunk.persona_id == gp_persona.id).all()
        assert len(gp_after) == 1 and gp_after[0].content == orig, \
            "Grandparent memory must not be modified"
        print("   [PASS] three-level retrieval OK, grandparent read-only protected")
    finally:
        db.rollback()
        for pid in [c_persona and c_persona.id,
                    p_persona and p_persona.id,
                    gp_persona and gp_persona.id]:
            if pid:
                delete_persona_memories(pid, char_id, db)
        for sess in [c_sess, p_sess, gp_sess]:
            if sess:
                db.delete(sess)
        db.delete(char); db.commit(); db.close()
        print("   [CLEANUP] done")


def run_integration_test():
    print("\n[Integration Test] Memory dedup and COW fork")
    db = SessionLocal()
    char = Character(name="DeduplicationTestChar", description="test",
                     personality="test", first_mes="hi")
    db.add(char); db.commit(); db.refresh(char)
    char_id = char.id

    try:
        from services.infrastructure.clients import chroma_client
        chroma_client.delete_collection(name=f"character_{char_id}")
    except Exception:
        pass

    parent_sess = child_sess = None
    parent_persona = child_persona = None
    try:
        parent_sess = Session(title="parent-sess")
        db.add(parent_sess); db.commit(); db.refresh(parent_sess)
        parent_persona = SessionPersona(session_id=parent_sess.id, character_id=char_id,
                                         current_mood="n", affection_score=0)
        db.add(parent_persona); db.commit(); db.refresh(parent_persona)

        db.add_all([
            ChatMessage(session_id=parent_sess.id, role=MessageRole.user,
                        content="Hi I am Xiao Ming, I like strawberry cake."),
            ChatMessage(session_id=parent_sess.id, role=MessageRole.assistant,
                        content="Hi Xiao Ming, noted you like strawberry cake."),
        ])
        db.commit()

        count = summarize_and_store_memory(parent_sess.id, db)
        print(f"  parent: {count} memories")
        pchunks = db.query(MemoryChunk).filter(
            MemoryChunk.persona_id == parent_persona.id).all()
        assert len(pchunks) > 0
        saved = pchunks[0].content

        child_sess = Session(title="child-sess", parent_session_id=parent_sess.id)
        db.add(child_sess); db.commit(); db.refresh(child_sess)
        child_persona = SessionPersona(session_id=child_sess.id, character_id=char_id,
                                        parent_persona_id=parent_persona.id,
                                        current_mood="n", affection_score=0)
        db.add(child_persona); db.commit(); db.refresh(child_persona)

        db.add_all([
            ChatMessage(session_id=child_sess.id, role=MessageRole.user,
                        content="I really love strawberry cake, especially with hot milk."),
            ChatMessage(session_id=child_sess.id, role=MessageRole.assistant,
                        content="Strawberry cake with milk is a great combo!"),
        ])
        db.commit()

        count2 = summarize_and_store_memory(child_sess.id, db)
        print(f"  child: {count2} memories")
        cchunks = db.query(MemoryChunk).filter(
            MemoryChunk.persona_id == child_persona.id).all()
        assert len(cchunks) > 0, "child must have local memories after COW"

        pafter = db.query(MemoryChunk).filter(
            MemoryChunk.persona_id == parent_persona.id).all()
        assert len(pafter) == len(pchunks) and pafter[0].content == saved
        print("  [PASS] parent read-only OK")

        recalled = retrieve_memories(persona_id=child_persona.id, character_id=char_id,
                                      query="What cake does Xiao Ming like?",
                                      db=db, top_k=5, min_importance=0.0)
        cake = [m for m in recalled if "strawberry" in m["content"].lower()]
        assert len(cake) <= 1, f"retrieval dedup failed: {len(cake)} duplicates"
        print(f"  [PASS] retrieval dedup OK (strawberry memories={len(cake)})")

    finally:
        db.rollback()
        for pid in [child_persona and child_persona.id,
                    parent_persona and parent_persona.id]:
            if pid:
                delete_persona_memories(pid, char_id, db)
        for sid in [child_sess and child_sess.id,
                    parent_sess and parent_sess.id]:
            if sid:
                db.query(ChatMessage).filter(
                    ChatMessage.session_id == sid).delete(synchronize_session="fetch")
        for sess in [child_sess, parent_sess]:
            if sess:
                db.delete(sess)
        db.delete(char); db.commit(); db.close()
        print("  [CLEANUP] done")
        print("\n[ALL TESTS PASSED]")


if __name__ == "__main__":
    test_relationship_classifier_fallback()
    test_multi_level_fork_cow()
    run_integration_test()
