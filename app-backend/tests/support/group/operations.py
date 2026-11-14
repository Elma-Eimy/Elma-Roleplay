"""群聊请求、调用快照与候选操作夹具。"""

import asyncio
import json
from uuid import uuid4
from core.models import GroupRoundCandidate, GroupRoundOperation, Session
from services.conversation.group import operation_service as operations, history_service as history
from services.conversation.group.call_snapshot import GroupCallSnapshot
from services.infrastructure.llm_provider import GroupModelConnection
from tests.support.group import history as fixtures


class GroupOperationFixture:
    setUp = fixtures.GroupHistoryFixture.setUp
    group = fixtures.GroupHistoryFixture.group

    prepare = fixtures.GroupHistoryFixture.prepare

    def calls(self, ids):
        encoded = json.dumps(dict(model="fixture", max_tokens=128, temperature=0.7))
        return GroupCallSnapshot(encoded, tuple((pid, encoded) for pid in ids), 50, 30,
                                 GroupModelConnection("https://EXAMPLE.invalid/v1/", "never-persist-key"))

    def command(self, sid, kind="send", request_id=None, expected=None, **kwargs):
        if expected is None:
            group = self.db.get(Session, sid)
            latest = operations._latest(sid, self.db)
            candidate = self.db.get(GroupRoundCandidate, latest.selected_candidate_id) if latest else None
            expected = (group.group_revision, latest.id if latest else None,
                        candidate.id if candidate else None, candidate.revision if candidate else None)
        if kind == "send":
            kwargs.setdefault("user_content", "  原文 {{char}} 😀  ")
            kwargs.setdefault("call_snapshot", self.calls(history._members(sid, self.db)))
        return asyncio.run(operations.accept_group_operation(sid, request_id or str(uuid4()), kind, expected[0], self.db,
            observed_round_id=expected[1], observed_candidate_id=expected[2], observed_candidate_revision=expected[3], **kwargs))

    def settle(self, receipt, success=True):
        operation = self.db.get(GroupRoundOperation, receipt["operation_id"])
        candidate = self.db.get(GroupRoundCandidate, operation.candidate_id)
        operation.status = "succeeded" if success else "failed"
        candidate.status = "awaiting_confirmation" if success else "failed"
        candidate.checkpoint = "done" if success else "user_visibility"
        candidate.revision += 1
        self.db.commit()
