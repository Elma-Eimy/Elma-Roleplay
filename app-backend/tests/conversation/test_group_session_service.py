"""群聊快照独立、原子失败和资源归属；只使用虚构临时数据。"""
import asyncio
import json
import tempfile
import threading
import time
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor

from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker

from core.locking import get_session_lock, is_session_locked
from core.models import (Base, Character, Session, SessionPersona, ChatMessage, MessageRole, MemoryChunk,
    MemoryType, GroupPersonaOrigin, GroupInheritedMemorySnapshot, OutboxJob, MemoryExtractionJob,
    MemoryEventBuffer, GraphEntity, MemoryConsolidation, MemoryConsolidationSource, MemoryConsolidationScope)
from services.conversation.group import session_service as service
from services.conversation.group.session_service import GroupSessionDraft, GroupMember
from services.conversation.session_access import SessionKindConflict
from services.conversation.session_service import safe_delete_session, create_session_service, get_recent_sessions
from services.character_service import delete_character_service


class GroupSessionServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.engine = create_engine("sqlite:///" + (Path(self.directory.name) / "test.db").as_posix(),
                                    connect_args={"check_same_thread": False})
        self.addCleanup(self.engine.dispose)

        @event.listens_for(self.engine, "connect")
        def foreign_keys(connection, _):
            connection.execute("PRAGMA foreign_keys=ON")

        Base.metadata.create_all(self.engine)
        self.sessions = sessionmaker(bind=self.engine, autoflush=False)
        self.db = self.sessions()
        self.addCleanup(self.db.close)
        self.db.add_all([Character(id=i, name=f"actor{i}", description="fixture", scenario="town", first_mes="hello") for i in (1, 2, 3)])
        self.db.add(Session(id=10, title="source"))
        self.db.flush()
        self.db.add(SessionPersona(id=100, session_id=10, character_id=1, affection_score=37,
                     current_mood="开心", cognition_state="knows user", current_scenario_override="library"))
        self.db.add_all([ChatMessage(id=1, session_id=10, role=MessageRole.user, content="first"),
                        ChatMessage(id=2, session_id=10, role=MessageRole.assistant, content="confirmed"),
                        ChatMessage(id=3, session_id=10, role=MessageRole.user, content="next"),
                        ChatMessage(id=4, session_id=10, role=MessageRole.assistant, content="latest",
                                    role_state_patch='{"scene":"current room"}')])
        self.db.flush()
        self.db.add_all([
            MemoryChunk(id=1, persona_id=100, content="confirmed fact", memory_type=MemoryType.fact,
                        origin_session_id=10, source_message_id=2, importance_score=0.9),
            MemoryChunk(id=2, persona_id=100, content="unconfirmed fact", memory_type=MemoryType.fact,
                        origin_session_id=10, source_message_id=4),
            MemoryChunk(id=3, persona_id=100, content="manual fact", memory_type=MemoryType.fact),
        ])
        self.db.commit()
        self.cards = GroupSessionDraft((GroupMember(1), GroupMember(2)))
        self.imported = replace(self.cards, members=(GroupMember(1, "single_snapshot", 10), GroupMember(2)))

    def create(self, draft=None):
        return asyncio.run(service.create_group_session(draft or self.imported, self.db))

    def snapshot(self):
        return {table: self.db.execute(text('SELECT * FROM "' + table + '" ORDER BY 1')).all()
                for table in Base.metadata.tables}

    def test_card_members_are_independent_without_generated_messages_or_progress(self):
        for size in (2, 3):
            result = self.create(GroupSessionDraft(tuple(GroupMember(i) for i in range(1, size + 1)), shared_setting="  "))
            group = self.db.get(Session, result["session_id"])
            self.assertIsNone(group.persona)
            self.assertIsNone(group.parent_session_id)
            self.assertIsNone(group.fork_message_id)
            self.assertIsNone(group.shared_setting)
            self.assertFalse(result["can_generate"])
            self.assertEqual(list(range(1, size + 1)), [p.member_slot for p in group.personas])
            for persona in group.personas:
                self.assertIsNone(persona.parent_persona_id)
                self.assertIsNone(persona.last_summarized_msg_id)
                self.assertIsNone(persona.last_cognition_update_msg_id)
                self.assertEqual("card", persona.group_origin.mode)
            self.assertEqual([], group.messages)
        self.assertEqual(0, self.db.query(MemoryExtractionJob).count())

    def test_saved_active_state_and_only_confirmed_effective_memories_are_frozen(self):
        result = self.create()
        persona = self.db.get(SessionPersona, result["members"][0]["persona_id"])
        self.assertEqual(37, persona.affection_score)
        self.assertEqual("开心", persona.current_mood)
        self.assertEqual("knows user", persona.cognition_state)
        self.assertEqual({"scene": "current room"}, json.loads(persona.role_state_base))
        origin = persona.group_origin
        self.assertEqual(4, origin.source_last_active_message_id)
        self.assertEqual(3, origin.source_confirmed_before_id)
        self.assertEqual({1, 3}, {card.source_memory_id for card in persona.inherited_memory_snapshots})
        before = [(card.source_memory_id, card.content, card.content_fingerprint) for card in persona.inherited_memory_snapshots]
        initial = origin.initial_state_json
        self.db.get(MemoryChunk, 1).content = "changed source"
        self.db.get(SessionPersona, 100).cognition_state = "new cognition"
        self.db.add(MemoryChunk(persona_id=100, content="new manual", memory_type=MemoryType.fact))
        self.db.commit()
        safe_delete_session(10, self.db)
        self.db.expire_all()
        persona = self.db.get(SessionPersona, persona.id)
        self.assertEqual(initial, persona.group_origin.initial_state_json)
        self.assertEqual(before, [(c.source_memory_id, c.content, c.content_fingerprint) for c in persona.inherited_memory_snapshots])
        self.assertEqual(2, service.get_group_session_detail(result["session_id"], self.db)["members"][0]["origin"]["inherited_memory_count"])
        self.assertEqual([], self.db.execute(text("PRAGMA foreign_key_check")).all())

    def test_branch_import_keeps_ancestor_fork_boundary(self):
        branch = create_session_service(1, 10, "branch", None, 2, self.db)
        result = self.create(replace(self.imported, members=(GroupMember(1, "single_snapshot", branch["session_id"]), GroupMember(2))))
        cards = self.db.query(GroupInheritedMemorySnapshot).filter_by(persona_id=result["members"][0]["persona_id"]).all()
        self.assertEqual({1, 3}, {card.source_memory_id for card in cards})
        self.assertNotIn(2, {card.source_memory_id for card in cards})

    def test_effective_consolidation_summary_stays_frozen_after_source_undo(self):
        batch = MemoryConsolidation(persona_id=100, status="applied", preview_json="{}")
        self.db.add(batch)
        self.db.flush()
        summary = MemoryChunk(persona_id=100, content="summary", memory_type=MemoryType.fact,
                              source_message_id=2, consolidation_id=batch.id)
        self.db.add(summary)
        self.db.flush()
        self.db.add_all([MemoryConsolidationSource(summary_id=summary.id, source_id=i) for i in (1, 3)])
        self.db.add(MemoryConsolidationScope(persona_id=100, consolidation_id=batch.id))
        self.db.commit()
        result = self.create()
        pid = result["members"][0]["persona_id"]
        self.assertEqual(["summary"], [m.content for m in self.db.query(GroupInheritedMemorySnapshot).filter_by(persona_id=pid)])
        self.db.delete(batch)
        self.db.commit()
        self.assertEqual(["summary"], [m.content for m in self.db.query(GroupInheritedMemorySnapshot).filter_by(persona_id=pid)])

    def test_bad_requests_missing_sources_and_type_conflicts_leave_no_partial_groups(self):
        cases = [
            (replace(self.cards, members=(GroupMember(1),)), service.GroupSessionValidationError),
            (replace(self.cards, members=(GroupMember(1), GroupMember(1))), service.GroupSessionValidationError),
            (replace(self.cards, title="x" * 51), service.GroupSessionValidationError),
            (replace(self.cards, members=(GroupMember(1, "card", 10), GroupMember(2))), service.GroupSessionValidationError),
            (replace(self.cards, members=(GroupMember(1, "single_snapshot", 999), GroupMember(2))), service.GroupSessionNotFound),
            (replace(self.cards, members=(GroupMember(2, "single_snapshot", 10), GroupMember(1))), service.GroupSessionValidationError),
            (replace(self.cards, members=(GroupMember(1), GroupMember(999))), service.GroupSessionNotFound),
        ]
        original = self.snapshot()
        for draft, error in cases:
            with self.subTest(draft=draft):
                with self.assertRaises(error):
                    self.create(draft)
                self.assertEqual(original, self.snapshot())
                self.assertFalse(is_session_locked(10))
        group = self.create(self.cards)
        with self.assertRaises(SessionKindConflict):
            self.create(replace(self.imported, members=(GroupMember(1, "single_snapshot", group["session_id"]), GroupMember(2))))

    def test_failure_in_second_member_and_commit_rolls_back_everything(self):
        original = self.snapshot()
        original_initial = service._initial_state
        def fail_second(character, source, db):
            if character.id == 2:
                raise RuntimeError("second member failed")
            return original_initial(character, source, db)
        with patch.object(service, "_initial_state", side_effect=fail_second):
            with self.assertRaisesRegex(RuntimeError, "second member"):
                self.create()
        self.assertEqual(original, self.snapshot())
        with patch.object(self.db, "commit", side_effect=RuntimeError("commit failed")):
            with self.assertRaisesRegex(RuntimeError, "commit failed"):
                self.create()
        self.assertEqual(original, self.snapshot())

    def test_busy_source_releases_any_previously_acquired_locks(self):
        self.db.add(Session(id=20))
        self.db.flush()
        self.db.add(SessionPersona(session_id=20, character_id=2))
        self.db.commit()
        async def scenario():
            lock = get_session_lock(20)
            await lock.acquire()
            try:
                with self.assertRaises(SessionKindConflict):
                    await service.create_group_session(replace(self.imported, members=(
                        GroupMember(2, "single_snapshot", 20), GroupMember(1, "single_snapshot", 10))), self.db)
                self.assertFalse(is_session_locked(10))
                self.assertTrue(lock.locked())
            finally:
                lock.release()
        asyncio.run(scenario())
        self.assertEqual(0, self.db.query(Session).filter_by(kind="group").count())

    def test_group_pagination_and_single_lists_do_not_mix_or_duplicate_members(self):
        ids = [self.create(self.cards)["session_id"] for _ in range(3)]
        page = service.list_group_sessions(self.db, limit=2)
        self.assertEqual(3, page["total"])
        self.assertEqual(ids[::-1][:2], [g["session_id"] for g in page["sessions"]])
        self.assertTrue(page["has_more"])
        self.assertEqual([ids[0]], [g["session_id"] for g in service.list_group_sessions(self.db, limit=2, offset=2)["sessions"]])
        self.assertEqual(1, get_recent_sessions(20, 0, self.db)["total"])
        self.assertNotIn('"content":', json.dumps(page))

    def test_group_delete_cascades_all_members_and_queues_only_local_resources(self):
        result = self.create()
        group_id = result["session_id"]
        pids = [member["persona_id"] for member in result["members"]]
        for pid in pids:
            self.db.add(MemoryChunk(persona_id=pid, content="local", memory_type=MemoryType.fact, chroma_doc_id=f"local_{pid}"))
            self.db.add(MemoryExtractionJob(persona_id=pid, kind="capture", payload_json="{}"))
            self.db.add(MemoryEventBuffer(persona_id=pid, payload_json="{}"))
            self.db.add(GraphEntity(persona_id=pid, name="place", entity_type="location"))
        self.db.add_all([ChatMessage(session_id=group_id, role=MessageRole.assistant, content="local", audio_path="local.mp3"),
                         ChatMessage(session_id=group_id, role=MessageRole.assistant, content="shared", audio_path="shared.mp3")])
        self.db.get(ChatMessage, 2).audio_path = "shared.mp3"
        self.db.commit()
        with self.assertRaises(SessionKindConflict):
            delete_character_service(1, self.db)
        deleted = asyncio.run(service.delete_group_session(group_id, self.db))
        self.assertEqual(2, deleted["members_deleted"])
        self.assertIsNotNone(self.db.get(Session, 10))
        for model in (GroupPersonaOrigin, GroupInheritedMemorySnapshot, MemoryExtractionJob, MemoryEventBuffer, GraphEntity):
            self.assertEqual(0, self.db.query(model).count())
        jobs = self.db.query(OutboxJob).all()
        self.assertEqual(2, len([j for j in jobs if j.task_type == "delete_vector"]))
        audio = [json.loads(j.payload)["file_paths"] for j in jobs if j.task_type == "delete_audio"]
        self.assertEqual([["local.mp3"]], audio)
        self.assertFalse(is_session_locked(group_id))
        self.assertEqual([], self.db.execute(text("PRAGMA foreign_key_check")).all())

    def test_outbox_failure_rolls_back_group_deletion(self):
        result = self.create()
        self.db.add(ChatMessage(session_id=result["session_id"], role=MessageRole.assistant, content="audio", audio_path="local.mp3"))
        self.db.commit()
        original = self.snapshot()
        with patch.object(service, "OutboxJob", side_effect=RuntimeError("outbox failed")):
            with self.assertRaisesRegex(RuntimeError, "outbox failed"):
                asyncio.run(service.delete_group_session(result["session_id"], self.db))
        self.assertEqual(original, self.snapshot())

    def test_cancellation_keeps_source_locked_until_database_thread_finishes(self):
        started, finish = threading.Event(), threading.Event()
        original_create = service._create
        def paused(draft, db):
            started.set()
            if not finish.wait(5):
                raise RuntimeError("test timed out")
            return original_create(draft, db)
        async def scenario():
            with patch.object(service, "_create", side_effect=paused):
                task = asyncio.create_task(service.create_group_session(self.imported, self.db))
                try:
                    for _ in range(500):
                        if started.is_set():
                            break
                        await asyncio.sleep(0.005)
                    self.assertTrue(started.is_set())
                    task.cancel()
                    await asyncio.sleep(0)
                    task.cancel()
                    await asyncio.sleep(0)
                    self.assertFalse(task.done())
                    self.assertTrue(is_session_locked(10))
                finally:
                    finish.set()
                with self.assertRaises(asyncio.CancelledError):
                    await task
                self.assertFalse(is_session_locked(10))
        asyncio.run(scenario())
        self.assertEqual(1, self.db.query(Session).filter_by(kind="group").count())

    def test_large_saved_memory_import_does_not_truncate(self):
        self.db.add_all([MemoryChunk(persona_id=100, content=f"saved fact {i}", memory_type=MemoryType.fact) for i in range(3000)])
        self.db.commit()
        started = time.monotonic()
        result = self.create()
        elapsed = time.monotonic() - started
        self.assertEqual(3002, result["members"][0]["origin"]["inherited_memory_count"])
        print(f"[GROUP SNAPSHOT] saved_cards=3002 elapsed_seconds={elapsed:.3f}")

    def test_snapshot_insert_failure_rolls_back_and_releases_source_lock(self):
        original = self.snapshot()
        def fail_snapshot(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("INSERT INTO group_inherited_memory_snapshots"):
                raise RuntimeError("snapshot failed")
        event.listen(self.engine, "before_cursor_execute", fail_snapshot)
        try:
            with self.assertRaisesRegex(RuntimeError, "snapshot failed"):
                self.create()
        finally:
            event.remove(self.engine, "before_cursor_execute", fail_snapshot)
        self.assertEqual(original, self.snapshot())
        self.assertFalse(is_session_locked(10))

    def test_missing_portrait_falls_back_without_changing_the_source(self):
        self.db.get(SessionPersona, 100).portrait_base = 999
        self.db.commit()
        result = self.create()
        self.assertEqual(0, result["members"][0]["state"]["portrait_base"])
        self.assertEqual(999, self.db.get(SessionPersona, 100).portrait_base)

    def test_creation_has_one_database_snapshot_during_concurrent_source_edits(self):
        original_initial = service._initial_state
        started = threading.Event()
        futures = []
        def edit_source():
            with self.engine.begin() as connection:
                started.set()
                connection.execute(text("UPDATE session_personas SET cognition_state='changed' WHERE id=100"))
                connection.execute(text("UPDATE memory_chunks SET content='changed' WHERE id=1"))
        with ThreadPoolExecutor(max_workers=1) as executor:
            def pause_after_state(character, source, db):
                state = original_initial(character, source, db)
                if source:
                    futures.append(executor.submit(edit_source))
                    self.assertTrue(started.wait(5))
                return state
            with patch.object(service, "_initial_state", side_effect=pause_after_state):
                result = self.create()
            for future in futures:
                future.result(timeout=5)
        self.db.expire_all()
        pid = result["members"][0]["persona_id"]
        self.assertEqual("knows user", self.db.get(SessionPersona, pid).cognition_state)
        card = self.db.query(GroupInheritedMemorySnapshot).filter_by(persona_id=pid, source_memory_id=1).one()
        self.assertEqual("confirmed fact", card.content)
        self.assertEqual("changed", self.db.get(MemoryChunk, 1).content)

    def test_character_deletion_rechecks_group_references_after_waiting_for_creation(self):
        original_initial = service._initial_state
        started = threading.Event()
        futures = []
        def delete_character():
            with self.sessions() as db:
                started.set()
                return delete_character_service(1, db)
        with ThreadPoolExecutor(max_workers=1) as executor:
            def start_deletion(character, source, db):
                if character.id == 1:
                    futures.append(executor.submit(delete_character))
                    self.assertTrue(started.wait(5))
                return original_initial(character, source, db)
            with patch.object(service, "_initial_state", side_effect=start_deletion):
                result = self.create()
            with self.assertRaises(SessionKindConflict):
                futures[0].result(timeout=5)
        self.assertIsNotNone(self.db.get(Character, 1))
        self.assertEqual(2, len(service.get_group_session_detail(result["session_id"], self.db)["members"]))

    def test_delete_busy_group_and_commit_failure_preserve_every_member(self):
        result = self.create()
        group_id = result["session_id"]
        original = self.snapshot()
        async def scenario():
            lock = get_session_lock(group_id)
            await lock.acquire()
            try:
                with self.assertRaises(SessionKindConflict):
                    await service.delete_group_session(group_id, self.db)
            finally:
                lock.release()
        asyncio.run(scenario())
        with patch.object(self.db, "commit", side_effect=RuntimeError("commit failed")):
            with self.assertRaisesRegex(RuntimeError, "commit failed"):
                asyncio.run(service.delete_group_session(group_id, self.db))
        self.assertEqual(original, self.snapshot())
        self.assertFalse(is_session_locked(group_id))
