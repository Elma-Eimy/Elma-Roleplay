r"""Offline tests for semantic memory-card extraction and provenance.

Run with:
    .\venv\Scripts\python.exe .\tests\memory\test_memory_card_extraction.py

The LLM, vector store, and graph store are replaced with local test doubles.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


ROOT = Path(__file__).resolve().parents[2]
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

        # 进入下一轮后，上述消息才成为可提纯的已确认历史；本条边界消息
        # 自身仍留在短期上下文，不应进入本批提纯。
        self.confirming_message = ChatMessage(
            session_id=self.session_id,
            role=MessageRole.user,
            content="Please continue.",
            is_active=True,
        )
        self.db.add(self.confirming_message)
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
            patch.object(memory_extraction_service, "retrieve_write_candidates", return_value=[]),
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
        self.assertNotIn(
            f"[\u6d88\u606fID={self.confirming_message.id}]",
            extraction_prompt,
        )

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

    def test_memory_transaction_failure_keeps_durable_candidates(self):
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
            patch.object(memory_extraction_service, "retrieve_write_candidates", return_value=[]),
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
        self.assertEqual(self.messages[-1].id, persona.last_summarized_msg_id)
        from core.models import MemoryExtractionJob
        self.assertEqual(1, self.db.query(MemoryExtractionJob).filter_by(status="retrying").count())

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
            patch.object(memory_extraction_service, "retrieve_write_candidates", return_value=[candidate]),
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
            patch.object(memory_extraction_service, "retrieve_write_candidates", return_value=[candidate]),
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

        self.assertEqual(0, count)
        add_mock.assert_not_called()
        self.assertEqual(
            1,
            self.db.query(MemoryChunk).filter(
                MemoryChunk.persona_id == self.persona.id
            ).count(),
        )


    def _write_candidate(self, content, **fields):
        row = MemoryChunk(persona_id=self.persona.id, origin_session_id=self.session_id,
                          content=content, memory_type=MemoryType.fact, importance_score=.4, **fields)
        self.db.add(row)
        self.db.flush()
        row.chroma_doc_id = f"mem_{row.id}"
        return row

    def _candidate_query(self, **kwargs):
        from services.memory.memory_write_candidates import retrieve_write_candidates
        return retrieve_write_candidates(
            self.persona.id, self.persona.character_id, "用户的猫叫豆包", self.db,
            memory_type=MemoryType.fact, temporal_status="unknown", temporal_note=None, **kwargs)

    def test_write_candidates_include_unindexed_recent_and_batch_cards(self):
        from services.memory import memory_write_candidates as candidates
        first = self._write_candidate("用户的猫叫豆包。")
        for index in range(14):
            self._write_candidate(f"独立事实 {index}")
        recent = self._write_candidate("用户叫自己的猫豆包。")
        collection = MagicMock()
        collection.query.return_value = {"ids": [[]], "distances": [[]]}
        with patch.object(candidates, "get_character_collection", return_value=collection):
            result = self._candidate_query(batch_ids=[first.id])
        self.assertIn(first.id, {item["id"] for item in result})
        self.assertIn(recent.id, {item["id"] for item in result})
        self.assertEqual(13, len(result))

    def test_write_candidates_recall_old_low_importance_by_distance(self):
        from services.memory import memory_write_candidates as candidates
        old = self._write_candidate("用户的猫叫豆包。")
        old.importance_score = .01
        for index in range(15):
            self._write_candidate(f"独立事实 {index}")
        collection = MagicMock()
        collection.query.return_value = {"ids": [[old.chroma_doc_id]], "distances": [[.01]]}
        with patch.object(candidates, "get_character_collection", return_value=collection):
            result = self._candidate_query()
        self.assertIn(old.id, {item["id"] for item in result})
        self.assertEqual(4, collection.query.call_args.kwargs["n_results"])
        self.assertNotIn(f"mem_{old.id + 15}", collection.query.call_args.kwargs["ids"])

    def test_vector_lookup_failure_does_not_become_an_empty_candidate_set(self):
        from services.memory import memory_write_candidates as candidates
        for index in range(14):
            self._write_candidate(f"已有事实 {index}")
        collection = MagicMock()
        collection.query.side_effect = RuntimeError("private provider response")
        with patch.object(candidates, "get_character_collection", return_value=collection), \
             self.assertLogs("uvicorn.error.memory_extraction", level="WARNING") as logs:
            with self.assertRaisesRegex(RuntimeError, "candidate lookup unavailable"):
                self._candidate_query()
        self.assertNotIn("private provider response", " ".join(logs.output))

    def test_distant_nearest_neighbors_still_reach_comparison_with_a_bounded_budget(self):
        from services.memory import memory_write_candidates as candidates
        old = [self._write_candidate(f"较早的独立事实 {index}") for index in range(4)]
        for index in range(15):
            self._write_candidate(f"近期的独立事实 {index}")
        collection = MagicMock()
        collection.query.return_value = {"ids": [[row.chroma_doc_id for row in reversed(old)]],
                                        "distances": [[.9, .7, .5, .3]]}
        with patch.object(candidates, "get_character_collection", return_value=collection), \
             patch.object(candidates.settings, "APP_DEDUP_WRITE_THRESHOLD", .15):
            result = self._candidate_query()
        selected = {item["id"] for item in result}
        self.assertTrue({old[0].id, old[1].id} <= selected)
        self.assertTrue({old[2].id, old[3].id}.isdisjoint(selected))
        self.assertEqual(14, len(result))

    def test_write_candidates_exclude_hidden_and_different_time_cards(self):
        old = self._write_candidate("用户住在北京。")
        current = self._write_candidate("用户住在杭州。", supersedes_id=old.id)
        self._write_candidate("用户计划搬家。", temporal_status="planned")
        self._write_candidate("用户过去搬过家。", temporal_note="去年")
        self.assertEqual([current.id], [item["id"] for item in self._candidate_query()])

    def test_write_candidates_respect_fork_and_other_story_boundaries(self):
        before = self._write_candidate("分叉之前的事实。", source_message_id=self.messages[0].id)
        self._write_candidate("分叉之后的事实。", source_message_id=self.messages[2].id)
        child_session = Session(title="child", parent_session_id=self.session_id,
                                fork_message_id=self.messages[1].id)
        self.db.add(child_session)
        self.db.flush()
        child = SessionPersona(session_id=child_session.id, character_id=self.persona.character_id,
                               parent_persona_id=self.persona.id)
        self.db.add(child)
        self.db.flush()
        from services.memory.memory_write_candidates import retrieve_write_candidates
        result = retrieve_write_candidates(child.id, child.character_id, "事实", self.db,
                                           memory_type=MemoryType.fact, temporal_status="unknown",
                                           temporal_note=None)
        self.assertEqual([before.id], [item["id"] for item in result])

    def test_semantic_batch_duplicate_is_reused_without_vector_sync(self):
        payload = {"memories": [
            {"content": "用户的猫叫豆包。", "memory_type": "fact", "importance_score": .4},
            {"content": "用户给家里的猫起名豆包。", "memory_type": "fact", "importance_score": .4},
        ], "entities": [], "relations": []}
        provider = self._provider_with_payload(payload)
        with patch.object(memory_extraction_service, "get_llm_provider", return_value=provider), \
             patch.object(memory_extraction_service, "resolve_memory_relationship_via_llm",
                          return_value={"relation": "same"}) as resolve, \
             self.assertLogs("uvicorn.error.memory_extraction", level="INFO") as logs:
            count = memory_extraction_service.summarize_and_store_memory(self.session_id, self.db)
        self.assertEqual(1, count)
        self.assertEqual(1, self.db.query(MemoryChunk).count())
        self.assertEqual(1, self.db.query(OutboxJob).count())
        resolve.assert_called_once()
        self.assertIn("new=1 replaced=0 reused=0 written=1", " ".join(logs.output))
        self.assertIn("new=0 replaced=0 reused=1 written=0", " ".join(logs.output))
        self.assertNotIn("豆包", " ".join(logs.output))

    def test_multiple_candidates_select_one_in_a_single_model_call(self):
        old = self._write_candidate("用户的猫叫豆包。")
        self._write_candidate("用户喜欢红茶。")
        self.db.commit()
        payload = {"memories": [{"content": "用户养的猫名为豆包。", "memory_type": "fact",
                                  "importance_score": .4}], "entities": [], "relations": []}
        extraction_response = self._provider_with_payload(payload).generate.return_value
        decision_response = self._provider_with_payload(
            {"relation": "same", "matched_memory_id": old.id}).generate.return_value
        provider = SimpleNamespace(generate=MagicMock(side_effect=[extraction_response, decision_response]))
        with patch.object(memory_extraction_service, "get_llm_provider", return_value=provider):
            count = memory_extraction_service.summarize_and_store_memory(self.session_id, self.db)
        self.assertEqual(0, count)
        self.assertEqual(2, provider.generate.call_count)
        self.assertEqual(2, self.db.query(MemoryChunk).count())

    def test_independent_or_opposite_batch_facts_can_coexist(self):
        payload = {"memories": [
            {"content": "用户喜欢红茶。", "memory_type": "fact", "importance_score": .4},
            {"content": "角色不喜欢红茶。", "memory_type": "fact", "importance_score": .4},
        ], "entities": [], "relations": []}
        with patch.object(memory_extraction_service, "get_llm_provider",
                          return_value=self._provider_with_payload(payload)), \
             patch.object(memory_extraction_service, "resolve_memory_relationship_via_llm",
                          return_value={"relation": "coexist"}):
            self.assertEqual(2, memory_extraction_service.summarize_and_store_memory(self.session_id, self.db))
        self.assertEqual(2, self.db.query(MemoryChunk).filter(MemoryChunk.supersedes_id.is_(None)).count())

    def test_decision_failure_isolated_and_durable_retry_reuses_written_card(self):
        payload = {"memories": [
            {"content": "用户的猫叫豆包。", "memory_type": "fact", "importance_score": .4},
            {"content": "用户给家里的猫起名豆包。", "memory_type": "fact", "importance_score": .4},
        ], "entities": [], "relations": []}
        provider = self._provider_with_payload(payload)
        with patch.object(memory_extraction_service, "get_llm_provider", return_value=provider), \
             patch.object(memory_extraction_service, "resolve_memory_relationship_via_llm",
                          side_effect=memory_extraction_service.MemoryDecisionDeferred("offline")):
            self.assertEqual(1, memory_extraction_service.summarize_and_store_memory(self.session_id, self.db))
        self.assertEqual(1, self.db.query(MemoryChunk).count())
        self.assertEqual(1, self.db.query(OutboxJob).count())
        self.db.refresh(self.persona)
        self.assertEqual(self.messages[-1].id, self.persona.last_summarized_msg_id)
        with patch.object(memory_extraction_service, "get_llm_provider", return_value=provider), \
             patch.object(memory_extraction_service, "resolve_memory_relationship_via_llm",
                          return_value={"relation": "same"}):
            self.assertEqual(0, memory_extraction_service.summarize_and_store_memory(self.session_id, self.db, flush_events=True))
        self.db.refresh(self.persona)
        self.assertEqual(self.messages[-1].id, self.persona.last_summarized_msg_id)

    def test_empty_extraction_checks_sources_before_advancing(self):
        provider = self._provider_with_payload({"memories": [], "entities": [], "relations": []})
        response = provider.generate.return_value

        def change_source(**_):
            self.messages[0].content = "原消息已被修改"
            self.db.commit()
            return response

        provider.generate.side_effect = change_source
        with patch.object(memory_extraction_service, "get_llm_provider", return_value=provider):
            self.assertEqual(0, memory_extraction_service.summarize_and_store_memory(self.session_id, self.db))
        self.db.refresh(self.persona)
        self.assertIsNone(self.persona.last_summarized_msg_id)

    def test_invalid_extraction_json_logs_metadata_without_model_text(self):
        provider = self._provider_with_payload({})
        provider.generate.return_value.choices[0].message.content = "private memory not json"
        with patch.object(memory_extraction_service, "get_llm_provider", return_value=provider), \
             self.assertLogs("uvicorn.error.memory_extraction", level="WARNING") as logs:
            self.assertEqual(0, memory_extraction_service.summarize_and_store_memory(self.session_id, self.db))
        self.assertIn("reason=invalid_json", " ".join(logs.output))
        self.assertNotIn("private memory", " ".join(logs.output))

    def test_multi_candidate_decision_rejects_foreign_id_and_invalid_json(self):
        candidates = [{"id": 10, "content": "用户的猫叫豆包。"},
                      {"id": 20, "content": "用户爱喝红茶。"}]
        for payload in ({"relation": "same", "matched_memory_id": 99},
                        {"relation": "replace", "matched_memory_id": 10, "resolved_content": ""},
                        {"relation": "invalid"}):
            with self.subTest(payload=payload), \
                 patch.object(memory_extraction_service, "get_llm_provider",
                              return_value=self._provider_with_payload(payload)):
                with self.assertRaises(memory_extraction_service.MemoryDecisionDeferred):
                    memory_extraction_service.resolve_memory_relationship_via_llm(candidates, "用户的猫名为豆包。")
        provider = self._provider_with_payload({"relation": "same", "matched_memory_id": 10})
        with patch.object(memory_extraction_service, "get_llm_provider", return_value=provider):
            decision = memory_extraction_service.resolve_memory_relationship_via_llm(candidates, "用户的猫名为豆包。")
        self.assertEqual(10, decision["matched_memory_id"])
        self.assertEqual("用户的猫叫豆包。", decision["resolved_content"])
        provider.generate.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
