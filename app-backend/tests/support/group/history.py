"""群聊历史准备与个人可见记录夹具。"""

import asyncio
from services.conversation.group import history_service as history
from services.conversation.group import session_service as groups
from tests.support.group import session_service as fixtures


class GroupHistoryFixture:
    setUp = fixtures.GroupSessionFixture.setUp
    snapshot = fixtures.GroupSessionFixture.snapshot

    def group(self):
        result = asyncio.run(groups.create_group_session(self.cards, self.db))
        return result["session_id"], tuple(member["persona_id"] for member in result["members"])

    def prepare(self, sid, visible, content="  用户原话 {{char}} <tag>  "):
        return asyncio.run(history.prepare_group_round(sid, content, visible, self.db))

    def append(self, sid, target, speaker, content, visible=()):
        result = asyncio.run(history.append_group_utterance(sid, target["candidate_id"], speaker,
            content, visible, target["revision"], self.db))
        target["revision"] = result["revision"]
        return result

    def read(self, sid, pid, target, before=100, **kwargs):
        return history.get_member_history(sid, pid, target["candidate_id"], before, self.db, **kwargs)
