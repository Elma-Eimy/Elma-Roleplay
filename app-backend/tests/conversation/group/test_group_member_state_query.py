"""候选状态读取的成员归属、成长上界与只读边界。"""
import asyncio
from datetime import datetime
import unittest

from core.models import (GroupContentItem, GroupMemberInsight, GroupMemoryCapture,
                         GroupRound, GroupRoundCandidate)
from services.conversation.group import query_service as queries, history_service as history
from services.conversation.group import session_service as groups
from tests.support.group import history as fixtures


class GroupMemberStateQueryTests(unittest.TestCase):
    setUp = fixtures.GroupHistoryFixture.setUp
    group = fixtures.GroupHistoryFixture.group
    prepare = fixtures.GroupHistoryFixture.prepare
    append = fixtures.GroupHistoryFixture.append
    snapshot = fixtures.GroupHistoryFixture.snapshot

    def test_candidate_state_replays_only_its_own_members_and_preserves_origin(self):
        group = asyncio.run(groups.create_group_session(self.imported, self.db))
        sid = group["session_id"]
        a, b = [m["persona_id"] for m in group["members"]]
        target = self.prepare(sid, (a, b))
        self.append(sid, target, a, "A 的当前发言", (b,))
        item = self.db.query(GroupContentItem).filter_by(candidate_id=target["candidate_id"], kind="utterance").one()
        item.affection_change, item.emotion_tag, item.role_state_patch = 5, "平静", '{"scene":"窗边"}'
        self.db.commit()
        baseline = self.snapshot()
        result = queries.get_group_candidate(sid, target["round_id"], target["candidate_id"], self.db)
        states = {m["persona_id"]: m for m in result["state_preview"]["members"]}
        self.assertEqual(group["members"][0]["state"]["affection_score"] + 5, states[a]["affection_score"])
        self.assertEqual("平静", states[a]["current_mood"])
        self.assertEqual("窗边", states[a]["role_state"]["scene"])
        self.assertEqual(group["members"][0]["state"]["cognition_state"], states[a]["cognition_state"])
        self.assertEqual(0, states[b]["affection_score"])
        self.assertNotEqual("窗边", states[b]["role_state"].get("scene"))
        self.assertEqual([], states[a]["insights"])
        self.assertEqual(baseline, self.snapshot())

    def test_unselected_sibling_does_not_read_selected_candidate_changes(self):
        sid, (a, b) = self.group()
        target = self.prepare(sid, (a, b))
        self.append(sid, target, a, "selected version", (b,))
        item = self.db.query(GroupContentItem).filter_by(candidate_id=target["candidate_id"], kind="utterance").one()
        item.affection_change = 3
        sibling = GroupRoundCandidate(session_id=sid, round_id=target["round_id"], version=2, status="awaiting_confirmation")
        self.db.add(sibling)
        self.db.commit()
        sibling_id = sibling.id
        result = queries.get_group_candidate(sid, target["round_id"], sibling_id, self.db)
        self.assertEqual(0, result["state_preview"]["members"][0]["affection_score"])
        other, _ = self.group()
        with self.assertRaises(groups.GroupSessionNotFound):
            queries.get_group_candidate(other, target["round_id"], sibling_id, self.db)

    def test_growth_is_owned_confirmed_and_bounded_by_candidate_watermark(self):
        sid, (a, b) = self.group()
        first = self.prepare(sid, (a, b))
        asyncio.run(history.finish_group_round(sid, first["candidate_id"], first["revision"], self.db))
        self.db.get(GroupRound, first["round_id"]).confirmed_at = datetime.utcnow()
        self.db.commit()
        target = self.prepare(sid, (a, b), "next round")
        captures = [GroupMemoryCapture(session_id=sid, round_id=first["round_id"],
                    candidate_id=first["candidate_id"], persona_id=pid, cards_json="[]") for pid in (a, b)]
        self.db.add_all(captures)
        self.db.flush()
        own = GroupMemberInsight(capture_id=captures[0].id, kind="member", target_persona_id=b,
                                 content="我仍信任 B", ref="1:0", quote="可见证据")
        foreign = GroupMemberInsight(capture_id=captures[1].id, kind="cognition", content="B_PRIVATE_INSIGHT",
                                     ref="2:0", quote="B 的证据")
        self.db.add_all([own, foreign])
        self.db.flush()
        candidate = self.db.get(GroupRoundCandidate, target["candidate_id"])
        candidate.insight_watermark = max(own.id, foreign.id)
        self.db.add(GroupMemberInsight(capture_id=captures[0].id, kind="cognition", content="LATE_INSIGHT",
                                      ref="1:0", quote="稍后处理"))
        self.db.commit()
        result = queries.get_group_candidate(sid, target["round_id"], target["candidate_id"], self.db)
        states = {m["persona_id"]: m for m in result["state_preview"]["members"]}
        self.assertEqual([dict(kind="member", content="我仍信任 B", target_persona_id=b, target_name="actor2")], states[a]["insights"])
        self.assertEqual(["B_PRIVATE_INSIGHT"], [r["content"] for r in states[b]["insights"]])
        self.assertNotIn("LATE_INSIGHT", str(states))
        self.assertNotIn("quote", str(states))
