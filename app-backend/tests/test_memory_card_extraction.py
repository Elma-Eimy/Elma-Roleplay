r"""Offline tests for semantic memory-card extraction and provenance.

Run with:
    .\venv\Scripts\python.exe .\tests\test_memory_card_extraction.py

The LLM, vector store, and graph store are replaced with local test doubles.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.models import (
    Base,
    Character,
    ChatMessage,
    MemoryType,
    MessageRole,
    MemoryChunk,
    OutboxJob,
    Session,
    SessionPersona,
)
from services.memory import memory_extraction_service, memory_manager
from services.infrastructure import outbox_worker


if sys.platform.startswith("win"):
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")


class MemoryCardExtractionTests(unittest.TestCase):
    def setUp(self):
        self.engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        Base.metadata.create_all(self.engine)
        self.db = sessionmaker(bind=self.engine)()

        character = Character(
            name="Lin Mo",
            description="A fictional investigator.",
            personality="calm",
            scenario="office",
            first_mes="Hello.",
        )
        session = Session(title="memory card test")
        self.db.add_all([character, session])
        self.db.flush()
        self.persona = SessionPersona(
            session_id=session.id,
            character_id=character.id,
            affection_score=0,
        )
        self.db.add(self.persona)
        self.db.commit()
        self.session_id = session.id

        self.messages = []
        for role, content in (
            (MessageRole.user, "I plan to move next month."),
            (MessageRole.assistant, "Is it because of work?"),
            (MessageRole.user, "Yes, to Hangzhou Binjiang for my new job."),
            (MessageRole.user, "My cat is named Doubao."),
        ):
            message = ChatMessage(
                session_id=self.session_id,
                role=role,
                content=content,
                is_active=True,
            )
            self.db.add(message)
            self.messages.append(message)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        self.engine.dispose()

    @staticmethod
    def _provider_with_payload(payload):
        content = json.dumps(payload, ensure_ascii=False)
        return SimpleNamespace(
            generate=MagicMock(
                return_value=SimpleNamespace(
                    choices=[SimpleNamespace(
                        message=SimpleNamespace(content=content)
                    )]
                )
            )
        )

    def test_normalizer_filters_fragments_greetings_and_batch_duplicates(self):
        first_id = self.messages[0].id
        last_id = self.messages[-1].id
        cards = memory_extraction_service.normalize_extracted_memories(
            [
                {
                    "content": "User plans to move to Hangzhou Binjiang next month for work.",
                    "memory_type": "event",
                    "importance_score": 0.8,
                    "source_start_message_id": first_id,
                    "source_end_message_id": self.messages[2].id,
                },
                {
                    "content": "User plans to move to Hangzhou Binjiang next month for work!",
                    "memory_type": "event",
                    "importance_score": 0.7,
                },
                {"content": "He will live there later.", "memory_type": "fact"},
                {"content": "thank you", "memory_type": "fact"},
                {
                    "content": "User's cat is named Doubao.",
                    "memory_type": "fact",
                    "importance_score": "bad score",
                    "source_start_message_id": 999999,
                    "source_end_message_id": 999999,
                },
            ],
            [message.id for message in self.messages],
        )

        self.assertEqual(2, len(cards))
        self.assertEqual(MemoryType.event, cards[0]["memory_type"])
        self.assertEqual(first_id, cards[0]["source_start_message_id"])
        self.assertEqual(self.messages[2].id, cards[0]["source_message_id"])
        self.assertEqual(0.5, cards[1]["importance_score"])
        self.assertEqual(first_id, cards[1]["source_start_message_id"])
        self.assertEqual(last_id, cards[1]["source_message_id"])

    def test_normalizer_keeps_substantive_pronouns_and_negation_pairs(self):
        message_ids = [message.id for message in self.messages]
        cards = memory_extraction_service.normalize_extracted_memories(
            [
                {
                    "content": "她因为用户送来的生日礼物感动得哭了。",
                    "memory_type": "emotion",
                },
                {"content": "她很好。", "memory_type": "emotion"},
                {
                    "content": "自从那件事情之后，她很喜欢用户。",
                    "memory_type": "relationship",
                },
                {
                    "content": "自从那件事情之后，她很不喜欢用户。",
                    "memory_type": "relationship",
                },
            ],
            message_ids,
        )

        self.assertEqual(3, len(cards))
        self.assertEqual(
            "她因为用户送来的生日礼物感动得哭了。",
            cards[0]["content"],
        )
        self.assertEqual(
            "自从那件事情之后，她很喜欢用户。",
            cards[1]["content"],
        )
        self.assertEqual(
            "自从那件事情之后，她很不喜欢用户。",
            cards[2]["content"],
        )

    def test_summarizer_writes_complete_cards_with_exact_source_ranges(self):
        payload = {
            "memories": [
                {
                    "content": "User plans to move to Hangzhou Binjiang next month for work.",
                    "memory_type": "event",
                    "importance_score": 0.7,
                    "source_start_message_id": self.messages[0].id,
                    "source_end_message_id": self.messages[2].id,
                },
                {
                    "content": "User's cat is named Doubao.",
                    "memory_type": "fact",
                    "importance_score": 0.6,
                    "source_start_message_id": self.messages[3].id,
                    "source_end_message_id": self.messages[3].id,
                },
                {"content": "He will live there.", "memory_type": "fact"},
                {"content": "hello", "memory_type": "fact"},
            ],
            "entities": [],
            "relations": [],
        }
        provider = self._provider_with_payload(payload)
        added_chunks = [
            SimpleNamespace(chroma_doc_id="mem_test_1"),
            SimpleNamespace(chroma_doc_id="mem_test_2"),
        ]

        with (
            patch.object(memory_extraction_service, "get_llm_provider", return_value=provider),
            patch.object(memory_extraction_service, "retrieve_memories", return_value=[]),
            patch.object(
                memory_extraction_service,
                "add_memory_chunk",
                side_effect=added_chunks,
            ) as add_mock,
            patch.object(memory_extraction_service, "upsert_graph_data"),
        ):
            count = memory_extraction_service.summarize_and_store_memory(
                self.session_id, self.db
            )

        self.assertEqual(2, count)
        self.assertEqual(2, add_mock.call_count)
        first_call = add_mock.call_args_list[0].kwargs
        second_call = add_mock.call_args_list[1].kwargs
        self.assertEqual(self.messages[0].id, first_call["source_start_message_id"])
        self.assertEqual(self.messages[2].id, first_call["source_message_id"])
        self.assertEqual(self.messages[3].id, second_call["source_start_message_id"])
        self.assertEqual(self.messages[3].id, second_call["source_message_id"])

        extraction_prompt = provider.generate.call_args.kwargs["messages"][1]["content"]
        for message in self.messages:
            self.assertIn(f"[\u6d88\u606fID={message.id}]", extraction_prompt)

        self.db.refresh(self.persona)
        self.assertEqual(self.messages[-1].id, self.persona.last_summarized_msg_id)

    def test_memory_chunk_persists_source_range_and_worker_syncs_metadata(self):
        collection = MagicMock()
        chunk = memory_manager.add_memory_chunk(
            persona_id=self.persona.id,
            character_id=self.persona.character_id,
            content="User plans to move to Hangzhou Binjiang next month for work.",
            memory_type=MemoryType.event,
            importance_score=0.7,
            origin_session_id=self.session_id,
            source_start_message_id=self.messages[0].id,
            source_message_id=self.messages[2].id,
            db=self.db,
        )

        self.assertEqual(self.messages[0].id, chunk.source_start_message_id)
        self.assertEqual(self.messages[2].id, chunk.source_message_id)
        job = self.db.query(OutboxJob).filter(
            OutboxJob.task_type == "upsert_vector"
        ).order_by(OutboxJob.id.desc()).first()
        self.assertIsNotNone(job)

        worker_db = sessionmaker(bind=self.engine)()
        with (
            patch.object(outbox_worker, "SessionLocal", return_value=worker_db),
            patch.object(
                memory_manager,
                "get_character_collection",
                return_value=collection,
            ),
        ):
            outbox_worker.handle_upsert_vector(job.payload)

        metadata = collection.upsert.call_args.kwargs["metadatas"][0]
        self.assertEqual(self.messages[0].id, metadata["source_start_message_id"])
        self.assertEqual(self.messages[2].id, metadata["source_message_id"])

    def test_memory_transaction_failure_does_not_advance_extraction_pointer(self):
        payload = {
            "memories": [{
                "content": "User plans to move to Hangzhou Binjiang next month for work.",
                "memory_type": "event",
                "importance_score": 0.7,
                "source_start_message_id": self.messages[0].id,
                "source_end_message_id": self.messages[2].id,
            }],
            "entities": [],
            "relations": [],
        }
        provider = self._provider_with_payload(payload)

        with (
            patch.object(memory_extraction_service, "get_llm_provider", return_value=provider),
            patch.object(memory_extraction_service, "retrieve_memories", return_value=[]),
            patch.object(
                memory_extraction_service,
                "add_memory_chunk",
                side_effect=RuntimeError("outbox enqueue failed"),
            ),
            patch.object(memory_extraction_service, "upsert_graph_data"),
        ):
            count = memory_extraction_service.summarize_and_store_memory(
                self.session_id, self.db
            )

        self.assertEqual(0, count)
        self.db.expire_all()
        persona = self.db.get(SessionPersona, self.persona.id)
        self.assertIsNone(persona.last_summarized_msg_id)

    def test_replace_creates_new_card_and_preserves_old_content_and_source(self):
        old = MemoryChunk(
            persona_id=self.persona.id,
            origin_session_id=self.session_id,
            source_start_message_id=self.messages[0].id,
            source_message_id=self.messages[0].id,
            content="User lives in Beijing.",
            memory_type=MemoryType.fact,
            importance_score=0.7,
            chroma_doc_id="mem_old",
        )
        self.db.add(old)
        self.db.commit()

        payload = {
            "memories": [{
                "content": "User now lives in Hangzhou.",
                "memory_type": "fact",
                "importance_score": 0.8,
                "source_start_message_id": self.messages[2].id,
                "source_end_message_id": self.messages[2].id,
            }],
            "entities": [],
            "relations": [],
        }
        provider = self._provider_with_payload(payload)
        collection = MagicMock()
        candidate = {
            "id": old.id,
            "content": old.content,
            "persona_id": self.persona.id,
            "importance_score": old.importance_score,
            "distance": 0.05,
        }

        with (
            patch.object(memory_extraction_service, "get_llm_provider", return_value=provider),
            patch.object(memory_extraction_service, "retrieve_memories", return_value=[candidate]),
            patch.object(
                memory_extraction_service,
                "resolve_memory_relationship_via_llm",
                return_value={
                    "relation": "replace",
                    "resolved_content": "User now lives in Hangzhou.",
                },
            ),
            patch.object(
                memory_extraction_service.cognition_service,
                "update_cognition_state",
            ),
            patch.object(
                memory_manager, "get_character_collection", return_value=collection
            ),
            patch.object(memory_extraction_service, "upsert_graph_data"),
        ):
            count = memory_extraction_service.summarize_and_store_memory(
                self.session_id, self.db
            )

        self.assertEqual(1, count)
        chunks = self.db.query(MemoryChunk).order_by(MemoryChunk.id).all()
        self.assertEqual(2, len(chunks))
        self.assertEqual("User lives in Beijing.", chunks[0].content)
        self.assertEqual(self.messages[0].id, chunks[0].source_message_id)
        self.assertEqual(old.id, chunks[1].supersedes_id)
        self.assertEqual("User now lives in Hangzhou.", chunks[1].content)
        self.assertEqual(self.messages[2].id, chunks[1].source_start_message_id)
        self.assertEqual(self.messages[2].id, chunks[1].source_message_id)

    def test_same_skips_duplicate_write(self):
        old = MemoryChunk(
            persona_id=self.persona.id,
            origin_session_id=self.session_id,
            content="User's cat is named Doubao.",
            memory_type=MemoryType.fact,
            importance_score=0.7,
            chroma_doc_id="mem_old",
        )
        self.db.add(old)
        self.db.commit()
        payload = {
            "memories": [{
                "content": "The user's cat is named Doubao.",
                "memory_type": "fact",
                "importance_score": 0.7,
                "source_start_message_id": self.messages[3].id,
                "source_end_message_id": self.messages[3].id,
            }],
            "entities": [],
            "relations": [],
        }
        provider = self._provider_with_payload(payload)
        candidate = {
            "id": old.id,
            "content": old.content,
            "persona_id": self.persona.id,
            "importance_score": old.importance_score,
            "distance": 0.04,
        }

        with (
            patch.object(memory_extraction_service, "get_llm_provider", return_value=provider),
            patch.object(memory_extraction_service, "retrieve_memories", return_value=[candidate]),
            patch.object(
                memory_extraction_service,
                "resolve_memory_relationship_via_llm",
                return_value={"relation": "same", "resolved_content": old.content},
            ),
            patch.object(memory_extraction_service, "add_memory_chunk") as add_mock,
            patch.object(memory_extraction_service, "upsert_graph_data"),
        ):
            count = memory_extraction_service.summarize_and_store_memory(
                self.session_id, self.db
            )

        self.assertEqual(1, count)
        add_mock.assert_not_called()
        self.assertEqual(
            1,
            self.db.query(MemoryChunk).filter(
                MemoryChunk.persona_id == self.persona.id
            ).count(),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
