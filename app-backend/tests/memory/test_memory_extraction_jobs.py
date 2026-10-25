"""Durable candidate retries, transaction boundaries, and provenance isolation."""
import json
import unittest
from datetime import datetime, timedelta
from unittest.mock import patch

from core.models import MemoryChunk, MemoryType, MemoryExtractionJob, Character, ChatMessage, GraphEntity
from services.memory import memory_extraction_service as extraction
from services.memory.memory_extraction_jobs import process_due_jobs, processing_status, pending_context
from services.memory.memory_event_buffer import load_event_snapshot, event_context
from tests.memory import test_memory_event_buffer as fixture


class ExtractionJobTests(unittest.TestCase):
    setUp = fixture.MemoryEventBufferTests.setUp
    tearDown = fixture.MemoryEventBufferTests.tearDown
    advance = fixture.MemoryEventBufferTests.advance
    card = fixture.MemoryEventBufferTests.card
    extract = fixture.MemoryEventBufferTests.extract
    buffer = fixture.MemoryEventBufferTests.buffer

    def old_fact(self, text, status="unknown", note=None):
        chunk = MemoryChunk(persona_id=self.persona.id, origin_session_id=self.session_id,
                            content=text, memory_type=MemoryType.fact, importance_score=.4,
                            temporal_status=status, temporal_note=note)
        self.db.add(chunk)
        self.db.commit()
        return chunk

    def test_model_decision_has_no_transaction_and_allows_an_independent_writer(self):
        self.old_fact("User prefers coffee.")
        cards = [self.card(), self.card("User prefers hot coffee.", memory_type="fact", event_status="complete")]
        calls = []

        def decide(*_):
            calls.append(True)
            self.assertFalse(self.db.in_transaction())
            other = self.factory()
            try:
                other.query(Character).update({Character.description: "independent writer"})
                other.commit()
            finally:
                other.close()
            return {"relation": "coexist"}

        # The fixture patches the resolver; set the callback on that mock through a separate payload provider.
        from tests.memory.test_memory_card_extraction import MemoryCardExtractionTests
        provider = MemoryCardExtractionTests._provider_with_payload({"memories": cards, "entities": [], "relations": []})
        with patch.object(extraction, "get_llm_provider", return_value=provider), \
             patch.object(extraction, "resolve_memory_relationship_via_llm", side_effect=decide):
            self.assertEqual(1, extraction.summarize_and_store_memory(self.session_id, self.db))
        self.assertEqual([True], calls)

    def test_vector_query_releases_read_transaction(self):
        from services.memory import memory_write_candidates
        from tests.memory.test_memory_card_extraction import MemoryCardExtractionTests
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        for index in range(14):
            chunk = self.old_fact(f"User knows independent fact {index}.")
            chunk.chroma_doc_id = f"mem_{chunk.id}"
        self.db.commit()
        checked = []

        def query(**_):
            self.assertFalse(self.db.in_transaction())
            checked.append(True)
            return {"ids": [[]], "distances": [[]]}

        provider = MemoryCardExtractionTests._provider_with_payload({"memories": [self.card(
            "User prefers coffee.", memory_type="fact", temporal_status="unknown", event_status="complete")],
            "entities": [], "relations": []})
        with patch.object(extraction, "get_llm_provider", return_value=provider), \
             patch.object(memory_write_candidates, "get_character_collection", return_value=SimpleNamespace(query=MagicMock(side_effect=query))), \
             patch.object(extraction, "resolve_memory_relationship_via_llm", return_value={"relation": "coexist"}):
            self.assertEqual(1, extraction.summarize_and_store_memory(self.session_id, self.db))
        self.assertEqual([True], checked)

    def test_failed_candidate_does_not_block_independent_event_and_retry_is_idempotent(self):
        self.old_fact("User prefers coffee.")
        cards = [self.card("User prefers hot coffee.", memory_type="fact", event_status="complete", temporal_status="unknown"),
                 self.card("User and Lin completed a beach visit.", event_status="complete")]
        from tests.memory.test_memory_card_extraction import MemoryCardExtractionTests
        provider = MemoryCardExtractionTests._provider_with_payload({"memories": cards, "entities": [], "relations": []})
        with patch.object(extraction, "get_llm_provider", return_value=provider), \
             patch.object(extraction, "resolve_memory_relationship_via_llm", side_effect=extraction.MemoryDecisionDeferred("offline")):
            self.assertEqual(1, extraction.summarize_and_store_memory(self.session_id, self.db))
        self.assertEqual("retrying", processing_status(self.persona.id, self.db)["status"])
        self.assertEqual(1, processing_status(self.persona.id, self.db)["pending_count"])
        self.assertEqual(self.source_ids[-1], self.persona.last_summarized_msg_id)
        self.assertEqual(1, len(pending_context(self.persona.id, self.db, self.current_user.id)))
        failed = self.db.query(MemoryExtractionJob).filter_by(status="retrying").one()
        failed.status = "processing"
        failed.lease_until = datetime.utcnow() - timedelta(seconds=1)
        failed.lease_token = "expired-process"
        self.db.commit()
        with patch.object(extraction, "get_llm_provider") as primary, \
             patch.object(extraction, "resolve_memory_relationship_via_llm", return_value={"relation": "same"}):
            self.assertEqual(0, process_due_jobs(self.db, self.persona.id))
            self.assertEqual(0, process_due_jobs(self.db, self.persona.id))
        primary.assert_not_called()
        self.assertEqual("completed", processing_status(self.persona.id, self.db)["status"])
        self.assertEqual(2, self.db.query(MemoryChunk).count())

    def test_same_content_with_more_precise_time_creates_a_version(self):
        old = self.old_fact("User lives in Hangzhou.")
        seen = []
        from tests.memory.test_memory_card_extraction import MemoryCardExtractionTests
        provider = MemoryCardExtractionTests._provider_with_payload({"memories": [self.card(
            "User lives in Hangzhou.", memory_type="fact", event_status="complete", temporal_status="current", temporal_note="Friday")],
            "entities": [], "relations": []})

        def same(candidates, new_card):
            seen.append((candidates, new_card))
            return {"relation": "same"}

        with patch.object(extraction, "get_llm_provider", return_value=provider), \
             patch.object(extraction, "resolve_memory_relationship_via_llm", side_effect=same):
            self.assertEqual(1, extraction.summarize_and_store_memory(self.session_id, self.db))
        self.assertEqual("Friday", seen[0][1]["temporal_note"])
        newer = self.db.query(MemoryChunk).filter(MemoryChunk.id != old.id).one()
        self.assertEqual(old.id, newer.supersedes_id)
        self.assertEqual(("current", "Friday"), (newer.temporal_status, newer.temporal_note))

    def test_auxiliary_graph_edit_does_not_invalidate_or_discard_event(self):
        event_card = self.card(source_start_message_id=self.source_ids[0], source_end_message_id=self.source_ids[0])
        fact_card = self.card("User prefers coffee.", memory_type="fact", event_status="complete",
                              source_start_message_id=self.source_ids[1], source_end_message_id=self.source_ids[1])
        self.assertEqual(1, self.extract([event_card, fact_card], entities=[{
            "name": "Cafe", "description": "Event plus preference", "memory_indices": [0, 1]}])[0])
        self.db.get(ChatMessage, self.source_ids[1]).content = "The coffee preference was corrected."
        self.db.commit()
        snapshot = load_event_snapshot(self.persona.id, self.db)
        self.assertEqual(1, len(event_context(snapshot)))
        self.assertEqual([], snapshot[0]["payload"]["entities"])
        self.assertEqual(1, extraction.summarize_and_store_memory(self.session_id, self.db, flush_events=True))
        self.assertEqual(0, self.db.query(GraphEntity).count())
        self.assertEqual(2, self.db.query(MemoryChunk).count())

    def test_manual_response_reports_retrying_instead_of_success(self):
        self.old_fact("User prefers coffee.")
        from tests.memory.test_memory_card_extraction import MemoryCardExtractionTests
        from routers.sessions import trigger_memory_summary
        provider = MemoryCardExtractionTests._provider_with_payload({"memories": [self.card(
            "User prefers hot coffee.", memory_type="fact", event_status="complete")], "entities": [], "relations": []})
        with patch.object(extraction, "get_llm_provider", return_value=provider), \
             patch.object(extraction, "resolve_memory_relationship_via_llm", side_effect=RuntimeError("private provider text")):
            response = trigger_memory_summary(self.session_id, self.db)
            self.assertEqual("pending", response["status"])
            provider.generate.assert_not_called()
            process_due_jobs(self.db, self.persona.id)
            process_due_jobs(self.db, self.persona.id)
            response = trigger_memory_summary(self.session_id, self.db)
        self.assertEqual("retrying", response["status"])
        self.assertGreaterEqual(response["pending_count"], 1)
        self.assertEqual(0, response["extracted_count"])
        self.assertNotIn("private", json.dumps(response))

    def test_capture_failure_retries_without_new_chat_messages(self):
        from tests.memory.test_memory_card_extraction import MemoryCardExtractionTests
        provider = MemoryCardExtractionTests._provider_with_payload({"memories": [self.card(event_status="complete")],
                                                                    "entities": [], "relations": []})
        with patch.object(extraction, "get_llm_provider", side_effect=ConnectionError("offline")):
            self.assertEqual(0, extraction.summarize_and_store_memory(self.session_id, self.db))
        self.assertEqual(1, self.db.query(MemoryExtractionJob).filter_by(kind="capture", status="retrying").count())
        self.assertIsNone(self.persona.last_summarized_msg_id)
        with patch.object(extraction, "get_llm_provider", return_value=provider):
            process_due_jobs(self.db, self.persona.id, force=True)
            self.assertEqual(1, process_due_jobs(self.db, self.persona.id))
            self.assertEqual(0, process_due_jobs(self.db, self.persona.id))
        self.assertEqual(1, self.db.query(MemoryChunk).count())
        provider.generate.assert_called_once()

    def test_manual_flush_marks_previously_captured_candidates_for_closure(self):
        from tests.memory.test_memory_card_extraction import MemoryCardExtractionTests
        from routers.sessions import trigger_memory_summary
        provider = MemoryCardExtractionTests._provider_with_payload({"memories": [self.card()], "entities": [], "relations": []})
        with patch.object(extraction, "get_llm_provider", return_value=provider):
            extraction.summarize_and_store_memory(self.session_id, self.db, _process=False)
        waiting = self.db.query(MemoryExtractionJob).one()
        waiting.status = "retrying"
        waiting.run_after = datetime.utcnow() + timedelta(hours=1)
        self.db.commit()
        with patch.object(extraction, "get_llm_provider") as model:
            trigger_memory_summary(self.session_id, self.db)
            process_due_jobs(self.db, self.persona.id)
            self.assertEqual(1, process_due_jobs(self.db, self.persona.id))
        model.assert_not_called()
        self.assertEqual(1, self.db.query(MemoryChunk).count())
        self.assertEqual("completed", processing_status(self.persona.id, self.db)["status"])

    def test_relation_model_receives_time_fields_without_internal_evidence(self):
        from tests.memory.test_memory_card_extraction import MemoryCardExtractionTests
        provider = MemoryCardExtractionTests._provider_with_payload({"relation": "same", "matched_memory_id": 9})
        old = {"id": 9, "content": "User lives in Hangzhou.", "temporal_status": "unknown", "temporal_note": None,
               "_source_evidence": [{"hash": "internal-evidence"}]}
        new = {"content": "User lives in Hangzhou.", "temporal_status": "current", "temporal_note": "Friday",
               "source_message_id": 10, "_source_evidence": [{"hash": "internal-evidence"}]}
        with patch.object(extraction, "get_llm_provider", return_value=provider):
            extraction.resolve_memory_relationship_via_llm([old], new)
        sent = json.loads(provider.generate.call_args.kwargs["messages"][1]["content"])
        self.assertEqual("unknown", sent["existing_memories"][0]["temporal_status"])
        self.assertEqual("Friday", sent["new_memory"]["temporal_note"])
        self.assertNotIn("internal-evidence", json.dumps(sent))

    def test_expired_processing_row_does_not_break_claiming_another_job(self):
        from tests.memory.test_memory_card_extraction import MemoryCardExtractionTests
        from services.memory.memory_extraction_jobs import _claim
        provider = MemoryCardExtractionTests._provider_with_payload({"memories": [
            self.card("User prefers coffee.", memory_type="fact", event_status="complete"),
            self.card("User owns a black cat.", memory_type="fact", event_status="complete")], "entities": [], "relations": []})
        with patch.object(extraction, "get_llm_provider", return_value=provider):
            extraction.summarize_and_store_memory(self.session_id, self.db, _process=False)
        first, second = self.db.query(MemoryExtractionJob).order_by(MemoryExtractionJob.id).all()
        first_id, second_id = first.id, second.id
        first.status = "processing"
        first.lease_until = datetime.utcnow() - timedelta(seconds=1)
        self.db.commit()
        self.assertIsNone(_claim(second_id, self.db))
        self.assertFalse(self.db.in_transaction())
        self.assertIsNotNone(_claim(first_id, self.db))
        self.assertIsNone(_claim(second_id, self.db))

    def test_backfilled_current_fact_becomes_historical_without_replacing_later_fact(self):
        from tests.memory.test_memory_card_extraction import MemoryCardExtractionTests
        provider = MemoryCardExtractionTests._provider_with_payload({"memories": [self.card(
            "User lives in Beijing.", memory_type="fact", temporal_status="current", event_status="complete")],
            "entities": [], "relations": []})
        with patch.object(extraction, "get_llm_provider", return_value=provider):
            extraction.summarize_and_store_memory(self.session_id, self.db, _process=False)
        self.advance("User has moved to Hangzhou.")
        newer = self.old_fact("User lives in Hangzhou.", status="current")
        newer.source_start_message_id = newer.source_message_id = newer.source_message_id_bound = self.source_ids[-1]
        self.db.commit()
        with patch.object(extraction, "resolve_memory_relationship_via_llm", return_value={
            "relation": "replace", "resolved_content": "User lives in Beijing."}):
            self.assertEqual(1, process_due_jobs(self.db, self.persona.id))
        older = self.db.query(MemoryChunk).filter(MemoryChunk.id != newer.id).one()
        self.assertEqual("historical", older.temporal_status)
        self.assertIsNone(older.supersedes_id)
        self.assertEqual("current", newer.temporal_status)

    def test_edit_before_processing_preserves_event_with_independent_sources(self):
        from tests.memory.test_memory_card_extraction import MemoryCardExtractionTests
        cards = [self.card(source_start_message_id=self.source_ids[0], source_end_message_id=self.source_ids[0]),
                 self.card("User prefers coffee.", memory_type="fact", event_status="complete",
                           source_start_message_id=self.source_ids[1], source_end_message_id=self.source_ids[1])]
        provider = MemoryCardExtractionTests._provider_with_payload({"memories": cards, "entities": [
            {"name": "Cafe", "memory_indices": [0, 1]}], "relations": []})
        with patch.object(extraction, "get_llm_provider", return_value=provider):
            extraction.summarize_and_store_memory(self.session_id, self.db, _process=False)
        self.db.get(ChatMessage, self.source_ids[1]).content = "Preference changed."
        self.db.commit()
        process_due_jobs(self.db, self.persona.id)
        self.assertEqual(1, len(event_context(load_event_snapshot(self.persona.id, self.db))))
        self.assertEqual(0, self.db.query(GraphEntity).count())
        self.assertEqual(0, self.db.query(MemoryChunk).count())
