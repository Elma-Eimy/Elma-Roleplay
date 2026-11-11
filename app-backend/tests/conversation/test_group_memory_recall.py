"""群聊继承卡只跟随本人的可见输入和候选策略进入个人 Prompt。"""
import asyncio
import json
import unittest

from application.group_runtime import group_runtime
from core.models import MemoryChunk, GroupRoundCandidate
from services.conversation import group_session_service as groups, group_history_service as history
from services.conversation.group_context_service import build_member_context
from services.conversation.group_unit_protocol import ContentUnit, UnitPlan
from tests.conversation import test_group_background as background


class GroupMemoryRecallTests(unittest.TestCase):
    setUp = background.GroupBackgroundTests.setUp
    observed = background.GroupBackgroundTests.observed
    submit = background.GroupBackgroundTests.submit
    drain = background.GroupBackgroundTests.drain

    def group(self, content="铜铃原定交给青鹭，暗记 Q17。"):
        card = self.db.get(MemoryChunk, 1)
        card.content = content
        card.temporal_status = "planned"
        card.temporal_note = "入群前的计划"
        self.db.get(MemoryChunk, 2).content = "铜铃未来密钥 FUTURE_ONLY"
        self.db.commit()
        group = asyncio.run(groups.create_group_session(self.imported, self.db))
        self.db.delete(card)
        self.db.commit()
        return group["session_id"], tuple(member["persona_id"] for member in group["members"])

    def test_send_uses_frozen_card_only_in_owners_role_call(self):
        sid, ids = self.group()
        user = "提到铜铃，你们想起什么？"
        model = background.Model(ids, steps=2, user=user)

        async def scenario(owner):
            receipt = await self.submit(sid, owner, model, user_content=user, max_steps=2)
            await self.drain(owner)
            candidate = self.db.get(GroupRoundCandidate, receipt["accepted"]["candidate_id"])
            self.assertEqual("awaiting_confirmation", candidate.status)
            self.assertTrue(json.loads(candidate.call_snapshot_json)["inherited_recall"])

        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))
        roles = [json.dumps(params["messages"], ensure_ascii=False) for stage, params in model.calls if stage == "role_generation"]
        self.assertEqual(2, len(roles))
        self.assertIn("暗记 Q17", roles[0])
        self.assertIn("入群前的计划", roles[0])
        self.assertNotIn("FUTURE_ONLY", roles[0])
        self.assertNotIn("暗记 Q17", roles[1])
        for stage, params in model.calls:
            if stage != "role_generation":
                self.assertNotIn("暗记 Q17", json.dumps(params["messages"], ensure_ascii=False))

    def test_hidden_or_discontinuous_trigger_and_old_policy_do_not_recall(self):
        sid, (a, b) = self.group()
        content = "铜隐藏铃"
        units = tuple(ContentUnit("user", start=start, end=end) for start, end in ((0, 1), (1, 3), (3, 4)))
        plan = UnitPlan(units, ((a, b), (b,), (a, b)))
        target = history._prepare(sid, content, (b,), self.db, unit_plan=plan, model="fixture")
        def prompt():
            return build_member_context(sid, a, target["candidate_id"], target["revision"], self.db).messages_json
        self.assertNotIn("暗记 Q17", prompt())
        reply = UnitPlan((ContentUnit("speech", "铜铃"),), ((a, b),))
        target.update(history._append(sid, target["candidate_id"], b, "铜铃", (a, b), target["revision"],
                                     self.db, unit_plan=reply, model="fixture"))
        self.assertIn("暗记 Q17", prompt())
        candidate = self.db.get(GroupRoundCandidate, target["candidate_id"])
        candidate.call_snapshot_json = json.dumps({"history_limit": 10})
        self.db.commit()
        self.assertNotIn("暗记 Q17", prompt())

    def test_correction_enters_only_later_candidates_and_only_for_its_owner(self):
        from services.memory.group_memory_capture import process_one_capture
        from services.memory.group_memory_index import unified_memories
        from unittest.mock import patch
        from core.models import GroupRecallCard
        old_content = "铜铃原定交给编号Q17的青鹭。"
        duplicate = self.db.get(MemoryChunk, 3)
        duplicate.content = old_content
        duplicate.temporal_status = "planned"
        duplicate.temporal_note = "入群前的计划"
        self.db.commit()
        sid, ids = self.group(old_content)
        user = "铜铃改交赤羽，原来的安排作废。"
        updated = "铜铃现归赤羽保管。"
        def extract(evidence):
            cards = []
            if evidence["persona_id"] == ids[0]:
                prior = next(row for row in evidence["prior_cards"] if "Q17" in row["content"])
                source = evidence["records"][0]
                cards = [dict(content=updated, ref=source["ref"], quote=source["text"], memory_type="fact",
                              temporal_status="current", replaces_id=prior["id"])]
            return {"insights": [], "cards": cards}
        async def scenario(owner):
            await self.submit(sid, owner, background.Model(ids, user=user), user_content=user)
            await self.drain(owner)
            question = "铜铃放在哪里？"
            old = await self.submit(sid, owner, background.Model(ids, user=question), user_content=question)
            await self.drain(owner)
            candidate = self.db.get(GroupRoundCandidate, old["accepted"]["candidate_id"])
            ceiling = json.loads(candidate.call_snapshot_json)["group_card_limit"]
            for _ in ids:
                with self.sessions() as db:
                    self.assertTrue(process_one_capture(db, extract=extract))
            local = self.db.query(GroupRecallCard).filter(GroupRecallCard.capture_id.isnot(None)).one()
            self.assertGreater(local.id, ceiling)
            from services.conversation.group_query_service import get_member_memories
            browsing = get_member_memories(sid, ids[0], self.db)
            self.assertIn(updated, str(browsing['items']))
            self.assertNotIn('Q17', str(browsing['items']))
            historical = get_member_memories(sid, ids[0], self.db, status='superseded')
            self.assertIn('Q17', str(historical['items']))
            earlier = unified_memories(ids[0], 2, ceiling, ["铜铃"], self.db, {})
            self.assertEqual(1, len(earlier))
            self.assertIn("Q17", str(earlier))
            self.assertNotIn(updated, str(earlier))
            local.indexed = True
            self.db.commit()
            model = background.Model(ids, user=question, steps=2)
            with patch("services.memory.group_memory_index.SemanticQuery.distances", return_value={local.id: 0.1}):
                await self.submit(sid, owner, model, kind="regenerate", max_steps=2)
                await self.drain(owner)
            prompts = [json.dumps(p["messages"], ensure_ascii=False) for stage, p in model.calls if stage == "role_generation"]
            self.assertEqual(2, len(prompts))
            self.assertIn(updated, prompts[0])
            self.assertNotIn("Q17", prompts[0])
            self.assertNotIn(updated, prompts[1])
            for stage, p in model.calls:
                if stage != "role_generation":
                    self.assertNotIn(updated, str(p["messages"]))
        with group_runtime(self.engine) as owner:
            asyncio.run(scenario(owner))

    def test_vector_sync_rebuild_and_late_upsert_after_group_deletion(self):
        from unittest.mock import Mock, patch
        from core.models import GroupRecallCard, OutboxJob
        from services.memory.group_memory_index import rebuild_group_index, sync_group_card, SemanticQuery
        sid, (a,b) = self.group()
        card = self.db.query(GroupRecallCard).filter_by(persona_id=a).first()
        card_id = card.id
        fake = Mock()
        collection = fake.get_or_create_collection.return_value
        fake.get_collection.return_value = collection
        with patch("services.infrastructure.clients.get_chroma_client", return_value=fake), patch(
                  "services.infrastructure.clients.get_embedding_function"):
            sync_group_card(card_id, self.sessions)
            self.db.refresh(card)
            self.assertTrue(card.indexed)
            key = f"gc_{card_id}"
            self.assertEqual([key], collection.upsert.call_args.kwargs["ids"])
            collection.query.return_value = {"ids":[[key,"mem_5","gc_77"]],"distances":[[0.2,0,0.98]]}
            self.assertEqual({card_id:0.2}, SemanticQuery(a,card_id,"线索").distances())
            rebuild_group_index(self.sessions)
            self.db.refresh(card)
            self.assertFalse(card.indexed)
            self.db.rollback()
            collection.upsert.side_effect = lambda **kw: asyncio.run(groups.delete_group_session(sid, self.db))
            sync_group_card(card_id,self.sessions)
            collection.delete.assert_called_with(ids=[key])
            sync_group_card(card_id,self.sessions)
            self.assertEqual(2, collection.delete.call_count)
            self.assertIsNone(self.db.get(GroupRecallCard,card_id))
            self.assertGreater(self.db.query(OutboxJob).filter_by(task_type="sync_group_card").count(),0)

    def test_compound_card_and_foreign_number_cannot_be_used_for_whole_card_replacement(self):
        from services.memory.group_memory_capture import process_one_capture, _validated_cards
        sid, ids = self.group()
        user = "铜铃要改交给赤羽了。"
        async def confirm(owner):
            await self.submit(sid, owner, background.Model(ids, user=user), user_content=user)
            await self.drain(owner)
            await self.submit(sid, owner, background.Model(ids))
            await self.drain(owner)
        with group_runtime(self.engine) as owner:
            asyncio.run(confirm(owner))
        observed = {}
        def extract(evidence):
            observed[evidence["persona_id"]] = evidence
            return {"cards": [], "insights": []}
        for _ in ids:
            with self.sessions() as db:
                self.assertTrue(process_one_capture(db, extract=extract))
        self.assertNotIn("Q17", str(observed[ids[0]]["prior_cards"]))
        self.assertEqual([], observed[ids[1]]["prior_cards"])
        for evidence in observed.values():
            record = evidence["records"][0]
            value = {"insights": [], "cards": [dict(content="保管人变更", memory_type="fact",
                temporal_status="current", quote=record["text"], ref=record["ref"], replaces_id=9999)]}
            with self.assertRaisesRegex(ValueError, "覆盖目标"):
                _validated_cards(value, evidence)
