r"""Manual DeepSeek quality sample for memory extraction.

This script uses the configured chat model but replaces vector and graph writes
with local test doubles. It prints extracted memories plus graph aliases and is
intentionally excluded from unittest discovery.

Run with:
    .\venv\Scripts\python.exe .\tests\manual_deepseek_memory_quality.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.models import (
    Base,
    Character,
    ChatMessage,
    MessageRole,
    Session,
    SessionPersona,
)
from services import cognition_service, graph_service, memory_manager


def main() -> None:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db = sessionmaker(bind=engine)()
    Base.metadata.create_all(engine)

    character = Character(
        name="林默",
        description="一名冷静但会认真兑现承诺的调查员。",
        personality="克制、敏锐",
        scenario="调查事务所",
        first_mes="晚上好。",
    )
    session = Session(title="manual memory quality")
    db.add_all([character, session])
    db.flush()
    persona = SessionPersona(
        session_id=session.id,
        character_id=character.id,
    )
    db.add(persona)
    db.flush()
    db.add_all([
        ChatMessage(
            session_id=session.id,
            role=MessageRole.user,
            content="我妹妹林晓最近很紧张，大家都叫她小鹿。",
            is_active=True,
        ),
        ChatMessage(
            session_id=session.id,
            role=MessageRole.assistant,
            content="她是在担心明年去杭州读书吗？",
            is_active=True,
        ),
        ChatMessage(
            session_id=session.id,
            role=MessageRole.user,
            content="对，她还没决定具体学校。",
            is_active=True,
        ),
        ChatMessage(
            session_id=session.id,
            role=MessageRole.assistant,
            content="我答应你，等她决定学校后会陪你一起准备。",
            is_active=True,
        ),
    ])
    db.commit()

    captured = []
    captured_graph = {"entities": [], "relations": []}

    def fake_add_memory_chunk(**kwargs):
        captured.append(kwargs)
        index = len(captured)
        return SimpleNamespace(id=index, chroma_doc_id=f"manual_{index}")

    def fake_upsert_graph_data(**kwargs):
        captured_graph["entities"] = kwargs.get("entities", [])
        captured_graph["relations"] = kwargs.get("relations", [])

    with (
        patch.object(memory_manager, "retrieve_memories", return_value=[]),
        patch.object(
            memory_manager,
            "add_memory_chunk",
            side_effect=fake_add_memory_chunk,
        ),
        patch.object(
            graph_service,
            "upsert_graph_data",
            side_effect=fake_upsert_graph_data,
        ),
        patch.object(cognition_service, "update_cognition_state"),
    ):
        count = cognition_service.summarize_and_store_memory(session.id, db)

    result = {
        "count": count,
        "memories": [
            {
                "content": item["content"],
                "memory_type": item["memory_type"].value,
                "importance_score": item["importance_score"],
                "source_start_message_id": item["source_start_message_id"],
                "source_message_id": item["source_message_id"],
            }
            for item in captured
        ],
        "graph": captured_graph,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    db.close()
    engine.dispose()


if __name__ == "__main__":
    main()
