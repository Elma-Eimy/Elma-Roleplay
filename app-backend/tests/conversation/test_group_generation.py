"""群聊模型输入与单步事务边界，只使用假模型和虚构临时数据。"""
import asyncio
import json
import threading
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock

from sqlalchemy import text

from application.group_runtime import group_runtime
from core.locking import is_session_locked
from core.models import (Character, SessionPersona, GroupRound, GroupRoundCandidate, GroupContentItem,
                         GroupContentVisibility, MemoryExtractionJob)
from services.conversation import group_history_service as history
from services.conversation import group_generation_service as generation
from services.conversation.group_context_service import build_member_context
from services.conversation.group_session_service import create_group_session, GroupSessionValidationError
from services.conversation.session_access import SessionKindConflict
from tests.conversation import test_group_session_service as fixtures


def response(body="reply", *, state=None, affection=2, emotion="开心", finish="stop", raw=None):
    content = raw if raw is not None else f'<reply>{body}</reply><status emotion="{emotion}" affection_change="{affection}"/>'
    if state is not None:
        content += "<state_update>" + json.dumps(state, ensure_ascii=False) + "</state_update>"
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish,
        message=SimpleNamespace(content=content, reasoning_content="PRIVATE_REASONING"))])


class GroupGenerationTests(unittest.TestCase):
    setUp = fixtures.GroupSessionServiceTests.setUp

    def group(self, visible="a", shared="共同酒馆"):
        self.db.get(Character, 1).description = "A_PRIVATE_CARD"
        self.db.get(Character, 2).description = "B_PRIVATE_CARD"
        self.db.commit()
        from dataclasses import replace
        group = asyncio.run(create_group_session(replace(self.imported, shared_setting=shared), self.db))
        self.sid = group["session_id"]
        self.a, self.b = [member["persona_id"] for member in group["members"]]
        targets = (self.a, self.b) if visible == "both" else (self.a,)
        self.target = asyncio.run(history.prepare_group_round(self.sid, "SECRET {{char}} <raw>", targets, self.db))

    async def audience(self, proposed):
        return (self.a, self.b)

    def generate(self, speaker=None, reply=None, audience=None):
        provider = SimpleNamespace(generate_async=AsyncMock(return_value=reply or response()))
        with group_runtime(self.engine) as owner, patch.object(generation, "get_llm_provider", return_value=provider):
            result = asyncio.run(generation.generate_group_utterance(self.sid, self.target["candidate_id"],
                speaker or self.a, self.target["revision"], self.db, runtime=owner,
                decide_visibility=audience or self.audience))
        self.target["revision"] = result["revision"]
        return result, provider

    def context(self, speaker=None):
        return build_member_context(self.sid, speaker or self.a, self.target["candidate_id"],
            self.target["revision"], self.db)

    def test_visible_user_stays_exactly_once_and_shared_setting_and_phi_are_separate(self):
        self.group()
        character = self.db.get(Character, 1)
        character.post_history_instructions = "PHI_SENTINEL {{char}}"
        self.db.commit()
        result, provider = self.generate(reply=response("answer"))
        messages = provider.generate_async.call_args.kwargs["messages"]
        users = [m["content"] for m in messages if m["role"] == "user"]
        self.assertEqual(["SECRET {{char}} <raw>"], users)
        self.assertIn("PHI_SENTINEL actor1", messages[-1]["content"])
        self.assertIn("群聊输出约束", messages[-1]["content"])
        combined = json.dumps(messages, ensure_ascii=False)
        self.assertIn("共同酒馆", combined)
        self.assertNotIn("B_PRIVATE_CARD", combined)
        self.assertNotIn("PRIVATE_REASONING", combined)
        item = self.db.get(GroupContentItem, result["item_id"])
        self.assertEqual("answer", item.content)
        self.assertEqual(2, item.affection_change)
        self.assertEqual(37, self.db.get(SessionPersona, self.a).affection_score)
        self.assertEqual(0, self.db.query(MemoryExtractionJob).count())

    def test_a_b_a_uses_individual_history_and_only_own_state_deltas(self):
        self.group()
        self.generate(reply=response("A_PUBLIC", state={"scene": "A_NEW_SCENE", "characters": {"actor1": {"posture": "站立"}}}))
        context = self.context(self.b)
        text_ = context.messages_json
        for secret in ("SECRET", "A_PRIVATE_CARD", "knows user", "A_NEW_SCENE", "PRIVATE_REASONING"):
            self.assertNotIn(secret, text_)
        self.assertIn("A_PUBLIC", text_)
        self.assertNotIn("scene", json.loads(context.state_json))
        self.assertIn("共同酒馆", text_)
        self.generate(self.b, response("B_PUBLIC", emotion="B_PRIVATE_MOOD", affection=-1))
        context = self.context(self.a)
        messages = json.loads(context.messages_json)
        self.assertIn("B_PUBLIC", context.messages_json)
        self.assertNotIn("B_PRIVATE_MOOD", context.messages_json)
        self.assertEqual("A_NEW_SCENE", json.loads(context.state_json)["scene"])
        own = [msg["content"] for msg in messages if msg["role"] == "assistant"]
        self.assertEqual(1, len(own))
        self.assertIn('affection_change="2"', own[0])
        self.generate(reply=response("A_AGAIN", affection=1))
        self.assertEqual([self.a, self.b, self.a], [item.speaker_persona_id for item in
            self.db.query(GroupContentItem).filter_by(kind="utterance").order_by(GroupContentItem.sequence)])

    def test_worldbook_scans_only_visible_content_and_preserves_card_example_macros(self):
        self.group()
        character = self.db.get(Character, 2)
        character.extensions = json.dumps({"character_book": {"entries": [
            {"keys": ["SECRET"], "content": "LEAKED_LORE", "enabled": True},
            {"keys": ["public"], "content": "VISIBLE_LORE", "enabled": True}]}})
        character.system_prompt_override = "{{original}} {{description}}"
        character.mes_example = "<START>\n{{user}}: example\n{{char}}: example reply"
        self.db.commit()
        self.generate(reply=response("public retelling"))
        context = self.context(self.b)
        self.assertNotIn("SECRET", context.messages_json)
        self.assertNotIn("LEAKED_LORE", context.messages_json)
        self.assertIn("VISIBLE_LORE", context.messages_json)
        self.assertIn("example reply", context.messages_json)
        self.assertIn("B_PRIVATE_CARD", context.messages_json)

    def test_no_visible_evidence_foreign_member_or_stale_revision_never_calls_model(self):
        self.group()
        for speaker, revision, error in ((self.b, 1, GroupSessionValidationError),
            (100, 1, GroupSessionValidationError), (self.a, 99, SessionKindConflict)):
            provider = SimpleNamespace(generate_async=AsyncMock())
            with group_runtime(self.engine) as owner, patch.object(generation, "get_llm_provider", return_value=provider):
                with self.assertRaises(error):
                    asyncio.run(generation.generate_group_utterance(self.sid, self.target["candidate_id"],
                        speaker, revision, self.db, runtime=owner, decide_visibility=self.audience))
            provider.generate_async.assert_not_called()
        self.assertFalse(is_session_locked(self.sid))

    def test_external_calls_have_no_database_transaction_and_hold_session_lock(self):
        self.group()
        async def model(**kwargs):
            self.assertFalse(self.db.connection().connection.driver_connection.in_transaction)
            self.assertTrue(is_session_locked(self.sid))
            with self.assertRaises(SessionKindConflict):
                await history.append_group_utterance(self.sid, self.target["candidate_id"], self.a, "racing", (), 1, self.db)
            return response()
        with group_runtime(self.engine) as owner, patch.object(generation, "get_llm_provider",
                return_value=SimpleNamespace(generate_async=model)):
            asyncio.run(generation.generate_group_utterance(self.sid, self.target["candidate_id"], self.a, 1,
                self.db, runtime=owner, decide_visibility=self.audience))
        self.assertFalse(is_session_locked(self.sid))

    def test_invalid_output_or_truncation_never_saves_fallback_dialogue(self):
        invalid = [response(raw="plain text"), response(""), response(affection=9), response(finish="length"),
            response(state={"characters": {"actor2": {"location": "secret"}}}), response(state={"unknown": "field"})]
        for reply in invalid:
            self.group()
            with self.assertRaises(generation.GroupGenerationError):
                self.generate(reply=reply)
            self.assertEqual(1, self.db.query(GroupContentItem).filter_by(candidate_id=self.target["candidate_id"]).count())
            self.assertEqual("failed", self.db.get(GroupRoundCandidate, self.target["candidate_id"]).status)
            self.assertFalse(is_session_locked(self.sid))

    def test_provider_and_audience_failure_keep_prefix_and_mark_failed(self):
        for stage in ("model", "audience"):
            self.group()
            self.generate(reply=response("prefix"))
            provider = SimpleNamespace(generate_async=AsyncMock(side_effect=RuntimeError("PRIVATE_ERROR"))
                if stage == "model" else AsyncMock(return_value=response("not saved")))
            async def bad_audience(proposed):
                raise RuntimeError("PRIVATE_AUDIENCE_ERROR")
            with group_runtime(self.engine) as owner, patch.object(generation, "get_llm_provider", return_value=provider):
                with self.assertRaisesRegex(generation.GroupGenerationError, "execution_failed"):
                    asyncio.run(generation.generate_group_utterance(self.sid, self.target["candidate_id"], self.a,
                        self.target["revision"], self.db, runtime=owner,
                        decide_visibility=bad_audience if stage == "audience" else self.audience))
            self.assertEqual(["prefix"], [row.content for row in self.db.query(GroupContentItem).filter_by(
                candidate_id=self.target["candidate_id"], kind="utterance")])
            self.assertEqual("failed", self.db.get(GroupRoundCandidate, self.target["candidate_id"]).status)

    def test_revision_changed_during_model_call_discards_late_result(self):
        self.group()
        async def model(**kwargs):
            with self.engine.begin() as connection:
                connection.execute(text("UPDATE group_round_candidates SET revision=99 WHERE id=:id"),
                    {"id": self.target["candidate_id"]})
            return response()
        with group_runtime(self.engine) as owner, patch.object(generation, "get_llm_provider",
                return_value=SimpleNamespace(generate_async=model)):
            with self.assertRaises(SessionKindConflict):
                asyncio.run(generation.generate_group_utterance(self.sid, self.target["candidate_id"], self.a, 1,
                    self.db, runtime=owner, decide_visibility=self.audience))
        self.db.expire_all()
        candidate = self.db.get(GroupRoundCandidate, self.target["candidate_id"])
        self.assertEqual((99, "generating"), (candidate.revision, candidate.status))
        self.assertEqual(1, self.db.query(GroupContentItem).count())

    def test_cancellation_during_model_marks_failed_without_resending(self):
        self.group()
        async def scenario(owner):
            started = asyncio.Event()
            async def model(**kwargs):
                started.set()
                await asyncio.Event().wait()
            provider = SimpleNamespace(generate_async=AsyncMock(side_effect=model))
            with patch.object(generation, "get_llm_provider", return_value=provider):
                work = asyncio.create_task(generation.generate_group_utterance(self.sid, self.target["candidate_id"],
                    self.a, 1, self.db, runtime=owner, decide_visibility=self.audience))
                await asyncio.wait_for(started.wait(), 2)
                work.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await work
                self.assertEqual(1, provider.generate_async.await_count)
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
        candidate = self.db.get(GroupRoundCandidate, self.target["candidate_id"])
        self.assertEqual(("failed", "cancelled"), (candidate.status, candidate.error_code))
        self.assertEqual(1, self.db.query(GroupContentItem).count())
        self.assertFalse(is_session_locked(self.sid))

    def test_cancellation_waits_for_dispatched_save_and_keeps_saved_prefix(self):
        self.group()
        started, release = threading.Event(), threading.Event()
        original = generation._save
        def paused(*args, **kwargs):
            started.set()
            if not release.wait(5):
                raise RuntimeError("test timeout")
            return original(*args, **kwargs)
        async def scenario(owner):
            with patch.object(generation, "get_llm_provider", return_value=SimpleNamespace(
                generate_async=AsyncMock(return_value=response("saved prefix")))), patch.object(generation, "_save", paused):
                work = asyncio.create_task(generation.generate_group_utterance(self.sid, self.target["candidate_id"],
                    self.a, 1, self.db, runtime=owner, decide_visibility=self.audience))
                try:
                    for _ in range(500):
                        if started.is_set():
                            break
                        await asyncio.sleep(0.005)
                    self.assertTrue(started.is_set())
                    work.cancel()
                    await asyncio.sleep(0)
                    work.cancel()
                    await asyncio.sleep(0)
                    self.assertTrue(is_session_locked(self.sid))
                    self.assertFalse(work.done())
                finally:
                    release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await work
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
        self.assertEqual("failed", self.db.get(GroupRoundCandidate, self.target["candidate_id"]).status)
        self.assertEqual(["saved prefix"], [row.content for row in self.db.query(GroupContentItem).filter_by(kind="utterance")])
        self.assertFalse(is_session_locked(self.sid))

    def test_expired_runtime_and_invalid_audience_cannot_commit(self):
        self.group()
        with group_runtime(self.engine) as owner:
            pass
        with self.assertRaises(RuntimeError):
            asyncio.run(generation.generate_group_utterance(self.sid, self.target["candidate_id"], self.a, 1,
                self.db, runtime=owner, decide_visibility=self.audience))
        async def invalid(proposed):
            return (100,)
        with self.assertRaises(GroupSessionValidationError):
            self.generate(audience=invalid)
        self.assertEqual(1, self.db.query(GroupContentItem).count())

    def test_commit_failure_rolls_back_state_and_visibility_and_records_failure(self):
        self.group()
        original = self.db.commit
        count = 0
        def commit():
            nonlocal count
            count += 1
            if count == 1:
                raise RuntimeError("injected commit failure")
            original()
        with patch.object(self.db, "commit", side_effect=commit):
            with self.assertRaises(generation.GroupGenerationError):
                self.generate(reply=response("failed", state={"scene": "not saved"}))
        self.assertEqual(1, self.db.query(GroupContentItem).count())
        self.assertEqual(2, self.db.query(GroupContentVisibility).count())
        self.assertEqual("failed", self.db.get(GroupRoundCandidate, self.target["candidate_id"]).status)

    def test_state_uses_all_own_confirmed_deltas_but_not_sibling_or_future_versions(self):
        self.group()
        self.generate(reply=response("chosen", state={"scene": "CHOSEN_SCENE"}))
        asyncio.run(history.finish_group_round(self.sid, self.target["candidate_id"], self.target["revision"], self.db))
        round_ = self.db.get(GroupRound, self.target["round_id"])
        round_.confirmed_at = datetime.utcnow()
        sibling = GroupRoundCandidate(round_id=round_.id, session_id=self.sid, version=2, status="awaiting_confirmation")
        self.db.add(sibling); self.db.flush()
        item = GroupContentItem(candidate_id=sibling.id, session_id=self.sid, sequence=1, kind="utterance",
            speaker_persona_id=self.a, content="SIBLING_BODY", role_state_patch='{"scene":"SIBLING_STATE"}')
        self.db.add(item); self.db.flush()
        self.db.add(GroupContentVisibility(item_id=item.id, session_id=self.sid, recipient_persona_id=self.a, decision="visible"))
        self.db.commit()
        self.target = asyncio.run(history.prepare_group_round(self.sid, "new user", (self.a,), self.db))
        future = GroupRound(session_id=self.sid, round_index=3, user_content="FUTURE_USER", confirmed_at=datetime.utcnow())
        self.db.add(future); self.db.flush()
        version = GroupRoundCandidate(round_id=future.id, session_id=self.sid, status="awaiting_confirmation")
        self.db.add(version); self.db.flush(); future.selected_candidate_id = version.id
        item = GroupContentItem(candidate_id=version.id, session_id=self.sid, sequence=1, kind="utterance",
            speaker_persona_id=self.a, content="FUTURE_BODY", role_state_patch='{"scene":"FUTURE_STATE"}')
        self.db.add(item); self.db.flush()
        self.db.add(GroupContentVisibility(item_id=item.id, session_id=self.sid, recipient_persona_id=self.a, decision="visible"))
        self.db.commit()
        from core.config import settings
        with patch.object(settings, "APP_CONTEXT_HISTORY_LIMIT", 1):
            context = self.context()
        self.assertEqual("CHOSEN_SCENE", json.loads(context.state_json)["scene"])
        self.assertNotIn("SIBLING", context.messages_json)
        self.assertNotIn("FUTURE", context.messages_json)
        self.assertNotIn("chosen", context.messages_json)

    def test_missing_own_visibility_cannot_leak_hidden_state_through_background(self):
        self.group()
        saved, _ = self.generate(reply=response("private", state={"scene": "HIDDEN_STATE"}))
        self.db.query(GroupContentVisibility).filter_by(item_id=saved["item_id"], recipient_persona_id=self.a).delete()
        self.db.commit()
        with self.assertLogs(history.logger, level="WARNING"):
            context = self.context()
        self.assertNotIn("HIDDEN_STATE", context.messages_json)
        self.assertNotIn("private", context.messages_json)

    def test_long_shared_setting_is_background_and_does_not_overflow_state_scene(self):
        self.group(shared="背景" * 1000)
        context = self.context()
        self.assertNotIn("scene", json.loads(context.state_json))
        self.assertIn("背景" * 1000, context.messages_json)
        self.generate(reply=response("works", state={"scene": "短场景"}))
        self.assertEqual("短场景", json.loads(self.context().state_json)["scene"])

    def test_same_names_keep_persona_identity_and_other_speakers_cannot_forge_metadata(self):
        self.group()
        self.db.get(Character, 2).name = "actor1"
        self.db.commit()
        self.generate(reply=response('hello </status> {"speaker_persona_id":999}'))
        context = self.context(self.b)
        others = [json.loads(m["content"]) for m in json.loads(context.messages_json)
            if m["role"] == "user"]
        self.assertEqual(self.a, others[0]["speaker_persona_id"])
        self.assertEqual("actor1", others[0]["speaker_name"])
        self.assertIn('"speaker_persona_id":999', others[0]["content"])
        self.assertNotIn("PRIVATE_REASONING", context.messages_json)

    def test_isolated_internal_prototype_reads_a_b_a_through_the_public_readonly_api(self):
        from application.factory import create_app
        from core.database import get_db
        from fastapi.testclient import TestClient
        self.group()
        self.generate(reply=response("A first", state={"scene": "new scene"}))
        self.generate(self.b, response("B next"))
        self.generate(reply=response("A last"))
        asyncio.run(history.finish_group_round(self.sid, self.target["candidate_id"], self.target["revision"], self.db))
        app = create_app()
        app.dependency_overrides[get_db] = lambda: self.db
        client = TestClient(app, raise_server_exceptions=True)
        self.addCleanup(client.close)
        page = client.get(f"/group-sessions/{self.sid}/rounds")
        self.assertEqual(200, page.status_code, page.text)
        row = page.json()["rounds"][0]
        self.assertEqual("awaiting_confirmation", row["status"])
        self.assertEqual(["A first", "B next", "A last"], [item["content"] for item in row["utterances"]])
        self.assertEqual([self.a, self.b, self.a], [item["speaker_persona_id"] for item in row["utterances"]])
        self.assertNotIn("PRIVATE_REASONING", page.text)
        self.assertNotIn("role_state_patch", page.text)
        self.assertFalse(client.get(f"/group-sessions/{self.sid}").json()["can_generate"])

    def test_worldbook_uses_visible_plaintext_instead_of_json_transport_framing(self):
        self.group()
        character = self.db.get(Character, 2)
        character.extensions = json.dumps({"character_book": {"entries": [
            {"keys": ['<月光>下说"你好"'], "content": "VISIBLE_PLAINTEXT_LORE", "enabled": True},
            {"keys": ["speaker_persona_id"], "content": "TRANSPORT_ONLY_LORE", "enabled": True}]}})
        self.db.commit()
        self.generate(reply=response('在<月光>下说"你好"'))
        context = self.context(self.b)
        self.assertIn("VISIBLE_PLAINTEXT_LORE", context.messages_json)
        self.assertNotIn("TRANSPORT_ONLY_LORE", context.messages_json)

    def test_cancelled_database_save_stays_cancelled_when_the_thread_fails(self):
        self.group()
        started, release = threading.Event(), threading.Event()
        def failed_save(*args, **kwargs):
            started.set()
            if not release.wait(5):
                raise RuntimeError("test timeout")
            raise RuntimeError("injected save failure after cancellation")
        async def scenario(owner):
            with patch.object(generation, "get_llm_provider", return_value=SimpleNamespace(
                generate_async=AsyncMock(return_value=response()))), patch.object(generation, "_save", failed_save):
                work = asyncio.create_task(generation.generate_group_utterance(self.sid, self.target["candidate_id"],
                    self.a, 1, self.db, runtime=owner, decide_visibility=self.audience))
                try:
                    for _ in range(500):
                        if started.is_set():
                            break
                        await asyncio.sleep(0.005)
                    self.assertTrue(started.is_set())
                    work.cancel()
                    await asyncio.sleep(0)
                    self.assertTrue(is_session_locked(self.sid))
                    self.assertFalse(work.done())
                finally:
                    release.set()
                with self.assertRaises(asyncio.CancelledError):
                    await work
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
        candidate = self.db.get(GroupRoundCandidate, self.target["candidate_id"])
        self.assertEqual(("failed", "cancelled"), (candidate.status, candidate.error_code))
        self.assertFalse(is_session_locked(self.sid))

    def test_failure_marker_error_does_not_replace_the_original_generation_error(self):
        self.group()
        with patch.object(self.db, "commit", side_effect=RuntimeError("PRIVATE_DB_ERROR")):
            with self.assertRaises(generation.GroupGenerationError) as caught:
                self.generate(reply=response(raw="invalid output"))
        self.assertEqual("invalid_output", caught.exception.code)
        self.assertNotIn("PRIVATE_DB_ERROR", str(caught.exception))
        self.assertEqual(1, self.db.query(GroupContentItem).count())
        self.assertFalse(is_session_locked(self.sid))

    def test_failure_marker_error_does_not_replace_cancellation(self):
        self.group()
        async def scenario(owner):
            started = asyncio.Event()
            async def model(**kwargs):
                started.set()
                await asyncio.Event().wait()
            with patch.object(generation, "get_llm_provider", return_value=SimpleNamespace(generate_async=model)), patch.object(
                self.db, "commit", side_effect=RuntimeError("PRIVATE_DB_ERROR")):
                work = asyncio.create_task(generation.generate_group_utterance(self.sid, self.target["candidate_id"],
                    self.a, 1, self.db, runtime=owner, decide_visibility=self.audience))
                await asyncio.wait_for(started.wait(), 2)
                work.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await work
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
        self.assertFalse(is_session_locked(self.sid))
