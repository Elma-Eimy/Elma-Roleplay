"""群聊可见单元、个人投影与发言依据夹具。"""

import asyncio
import json
from services.conversation.group import history_service as history
from services.conversation.group.session_service import create_group_session
from services.conversation.group.unit_protocol import ContentUnit, UnitPlan
from tests.support.group import session_service as fixtures


def grounding(messages):
    marker = '【本次发言依据】\n'
    return next(json.loads(row['content'].split(marker, 1)[1].split('\n', 1)[0])
                for row in messages if marker in row['content'])


class GroupUnitFixture:
    setUp = fixtures.GroupSessionFixture.setUp

    def group(self, user="😀公开。秘密{{char}}<raw>"):
        result = asyncio.run(create_group_session(self.imported, self.db))
        self.sid = result["session_id"]
        self.a, self.b = [row["persona_id"] for row in result["members"]]
        self.user = user
        self.plan = UnitPlan((ContentUnit("user", start=0, end=4), ContentUnit("user", start=4, end=len(user))),
                             ((self.a, self.b), (self.a,)))
        self.target = history._prepare(self.sid, user, (self.a,), self.db, unit_plan=self.plan, model="fixture")

    def append(self, speaker=None, *, patch_value=None, affection=2):
        speaker = speaker or self.a
        plan = UnitPlan((ContentUnit("speech", "桥坏了。"), ContentUnit("thought", "PRIVATE_THOUGHT")),
                        ((self.a, self.b), (speaker,)))
        result = history._append(self.sid, self.target["candidate_id"], speaker,
            "桥坏了。PRIVATE_THOUGHT", (speaker,), self.target["revision"], self.db,
            emotion_tag="紧张", affection_change=affection, role_state_patch=patch_value, unit_plan=plan, model="fixture")
        self.target["revision"] = result["revision"]
        return result

    def personal(self, pid, **kwargs):
        return history.get_member_history(self.sid, pid, self.target["candidate_id"], 100, self.db, **kwargs)
