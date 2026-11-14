"""群聊单步生成夹具与回复替身。"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch, AsyncMock
from application.group_runtime import group_runtime
from core.models import Character
from services.conversation.group import history_service as history
from services.conversation.group import generation_service as generation
from services.conversation.group.context_service import build_member_context
from services.conversation.group.session_service import create_group_session
from tests.support.group import session_service as fixtures


def response(body="reply", *, state=None, affection=2, emotion="开心", finish="stop", raw=None):
    content = raw if raw is not None else f'<reply>{body}</reply><status emotion="{emotion}" affection_change="{affection}"/>'
    if state is not None:
        content += "<state_update>" + json.dumps(state, ensure_ascii=False) + "</state_update>"
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason=finish,
        message=SimpleNamespace(content=content, reasoning_content="PRIVATE_REASONING"))])


class GroupGenerationFixture:
    setUp = fixtures.GroupSessionFixture.setUp

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
