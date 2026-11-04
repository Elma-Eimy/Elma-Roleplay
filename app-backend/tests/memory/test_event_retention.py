"""Fixed synthetic dialogue replay checks accepted facts, not model extraction quality."""
import json
import unittest
from pathlib import Path
from unittest.mock import patch

from core.models import ChatMessage, GraphEntity, MemoryChunk, MemoryEventBuffer, SessionPersona
from services.memory import memory_extraction_service as extraction
from services.memory.memory_event_buffer import event_context, load_event_snapshot
from tests.memory import test_memory_event_buffer as fixture


def retained_facts(facts, texts):
    return [any(all(any(alias in text for alias in group) for group in fact["anchors"])
                for text in texts) for fact in facts]


class EventRetentionTests(unittest.TestCase):
    setUp = fixture.MemoryEventBufferTests.setUp
    tearDown = fixture.MemoryEventBufferTests.tearDown
    advance = fixture.MemoryEventBufferTests.advance
    card = fixture.MemoryEventBufferTests.card
    extract = fixture.MemoryEventBufferTests.extract
    buffer = fixture.MemoryEventBufferTests.buffer
    fork = fixture.MemoryEventBufferTests.fork

    def test_fixed_dialogues_keep_all_accepted_facts_across_checkpoints_and_restart(self):
        cases = json.loads((Path(__file__).parents[1] / "fixtures/event_retention_cases.json").read_text(encoding="utf-8"))
        for case in cases["cases"]:
            with self.subTest(case=case["id"]):
                event_id = None
                first_memory_id = self.db.query(MemoryChunk).count()
                for index, batch in enumerate(case["batches"]):
                    if index or first_memory_id:
                        self.advance(batch["assistant"])
                    self.db.get(ChatMessage, self.source_ids[0]).content = batch["user"]
                    self.db.get(ChatMessage, self.source_ids[-1]).content = batch["assistant"]
                    self.db.commit()
                    last = index == len(case["batches"]) - 1
                    self.extract([self.card(batch["replay_delta"], buffer_id=event_id,
                                            event_status="complete" if last else "ongoing")])
                    if event_id is None:
                        event_id = self.db.query(MemoryEventBuffer).filter_by(status="open").one().id
                    if index == 2:
                        self.assertEqual("checkpointed", self.db.get(MemoryEventBuffer, event_id).status)
                        persona_id = self.persona.id
                        current_user_id = self.current_user.id
                        self.db.close()
                        self.db = self.factory()
                        self.persona = self.db.get(SessionPersona, persona_id)
                        self.current_user = self.db.get(ChatMessage, current_user_id)
                        self.assertIn(event_id, [item["buffer_id"] for item in event_context(load_event_snapshot(persona_id, self.db))])
                chunks = self.db.query(MemoryChunk).filter_by(event_id=event_id).all()
                self.assertEqual((len(case["batches"]) + 2) // 3, len(chunks))
                self.assertTrue(all(chunk.supersedes_id is None for chunk in chunks))
                checks = retained_facts(case["facts"], [chunk.content for chunk in chunks])
                self.assertTrue(all(checks), [fact["description"] for fact, kept in zip(case["facts"], checks) if not kept])
                # The last model delta deliberately omits early facts; a rewrite would fail.
                self.assertLess(sum(retained_facts(case["facts"], [case["batches"][-1]["replay_delta"]])), len(checks))
                self.assertEqual("closed", self.db.get(MemoryEventBuffer, event_id).status)
                with patch.object(extraction, "get_llm_provider") as provider:
                    self.assertEqual(0, extraction.summarize_and_store_memory(self.session_id, self.db, flush_events=True))
                provider.assert_not_called()
                print(f"[EVENT RETENTION] case={case['id']} accepted_fact_anchors={sum(checks)}/{len(checks)} stages={len(chunks)}")

    def test_capacity_checkpoint_resumes_same_identity_and_preserves_old_stage(self):
        self.extract([self.card(f"Independent ongoing event {index}.") for index in range(4)])
        checkpoint = self.db.query(MemoryEventBuffer).filter_by(status="checkpointed").one()
        event_id = checkpoint.id
        old = self.db.query(MemoryChunk).filter_by(event_id=event_id).one()
        old_id, old_text = old.id, old.content
        self.advance("The first event continues.")
        self.extract([self.card("The first event is now finished.", buffer_id=event_id, event_status="complete")])
        self.assertEqual(old_text, self.db.get(MemoryChunk, old_id).content)
        self.assertEqual(2, self.db.query(MemoryChunk).filter_by(event_id=event_id).count())
        self.assertEqual("closed", self.db.get(MemoryEventBuffer, event_id).status)

    def test_closed_and_foreign_event_ids_cannot_be_reopened(self):
        self.extract([self.card()])
        event_id = self.buffer().id
        self.advance()
        self.extract([self.card("The event ended.", buffer_id=event_id, event_status="complete")])
        pointer = self.persona.last_summarized_msg_id
        self.advance()
        self.assertEqual(0, self.extract([self.card(buffer_id=event_id)])[0])
        self.assertEqual(pointer, self.persona.last_summarized_msg_id)
        self.assertEqual("closed", self.db.get(MemoryEventBuffer, event_id).status)

    def test_parent_continuation_does_not_widen_child_visibility_of_same_identity(self):
        from services.memory.memory_visibility import memory_view
        self.extract([self.card("The beach visit began.")])
        event_id = self.buffer().id
        child_id = self.fork(self.current_user.id)
        first_stage = self.db.query(MemoryChunk).filter_by(event_id=event_id).one()
        first_stage_id = first_stage.id
        self.advance("The parent story later continues at a cafe.")
        self.extract([self.card("The parent visit ended at a cafe.", buffer_id=event_id, event_status="complete")])
        visible, hidden = memory_view(child_id, self.db)
        self.assertEqual([first_stage_id], [row.id for row in self.db.query(MemoryChunk).filter(
            visible, MemoryChunk.id.not_in(hidden), MemoryChunk.event_id == event_id).all()])
        self.assertEqual([], event_context(load_event_snapshot(child_id, self.db)))
        self.assertEqual(2, self.db.query(MemoryChunk).filter_by(event_id=event_id).count())

    def test_ordinary_card_cannot_replace_an_existing_event_checkpoint(self):
        from tests.memory.test_memory_card_extraction import MemoryCardExtractionTests
        self.extract([self.card("The old beach stage contained a precise promise.")])
        event_id = self.buffer().id
        extraction.summarize_and_store_memory(self.session_id, self.db, flush_events=True)
        old = self.db.query(MemoryChunk).one()
        old_id, old_text = old.id, old.content
        self.advance("Another event was completed.")
        provider = MemoryCardExtractionTests._provider_with_payload({"memories": [
            self.card("A newly completed event.", event_status="complete")], "entities": [], "relations": []})
        with patch.object(extraction, "get_llm_provider", return_value=provider), patch.object(
                extraction, "resolve_memory_relationship_via_llm", return_value={
                    "relation": "replace", "resolved_content": "A short rewritten scene."}):
            self.assertEqual(1, extraction.summarize_and_store_memory(self.session_id, self.db))
        self.assertEqual(old_text, self.db.get(MemoryChunk, old_id).content)
        self.assertEqual(1, self.db.query(MemoryChunk).filter_by(event_id=event_id).count())
        self.assertTrue(all(row.supersedes_id is None for row in self.db.query(MemoryChunk).all()))

    def test_auxiliary_edit_between_plan_and_commit_does_not_discard_event_stage(self):
        from services.memory import memory_extraction_jobs as jobs
        self.extract([
            self.card("The beach event is ongoing.", source_start_message_id=self.source_ids[0],
                      source_end_message_id=self.source_ids[0]),
            self.card("User prefers hot coffee.", memory_type="fact", event_status="complete",
                      source_start_message_id=self.source_ids[-1], source_end_message_id=self.source_ids[-1]),
        ], entities=[{"name": "Cafe", "description": "Joint evidence", "memory_indices": [0, 1]}])
        original_plan = jobs._plan

        def plan_then_edit(data, db):
            planned = original_plan(data, db)
            db.get(ChatMessage, self.source_ids[-1]).content = "The separate coffee preference was corrected."
            db.commit()
            return planned

        with patch.object(jobs, "_plan", side_effect=plan_then_edit):
            self.assertEqual(1, extraction.summarize_and_store_memory(self.session_id, self.db, flush_events=True))
        self.assertEqual(0, self.db.query(GraphEntity).count())
        self.assertEqual(2, self.db.query(MemoryChunk).count())

    def test_manually_changed_checkpoint_is_not_reinjected_from_old_identity_payload(self):
        self.extract([self.card("The original beach stage.")])
        event_id = self.buffer().id
        extraction.summarize_and_store_memory(self.session_id, self.db, flush_events=True)
        chunk = self.db.query(MemoryChunk).one()
        self.assertEqual(1, len(event_context(load_event_snapshot(self.persona.id, self.db))))
        chunk.content = "The user corrected the saved memory."
        self.db.commit()
        self.assertEqual([], event_context(load_event_snapshot(self.persona.id, self.db)))
        self.assertEqual(0, extraction.summarize_and_store_memory(self.session_id, self.db, flush_events=True))
        self.assertEqual("closed", self.db.get(MemoryEventBuffer, event_id).status)
        self.assertEqual("The user corrected the saved memory.", self.db.query(MemoryChunk).one().content)
