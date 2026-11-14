"""群聊后台执行夹具与导演、角色模型替身。"""

import asyncio
import json
from contextlib import contextmanager
from datetime import datetime, timedelta
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import event
from core.models import Session, GroupRoundCandidate
from services.conversation.group import background_service as background, checkpoint_service as checkpoints
from services.conversation.group import operation_service as operations
from services.conversation.group import round_service as rounds
from scripts.group_chat_prototype.worker import _response
from tests.support.group import operations as fixtures


class Model:
    def __init__(self, ids, *, fail=None, steps=1, text="NEW_REPLY", user="hello"):
        self.ids, self.fail, self.steps, self.text, self.user = ids, fail, steps, text, user
        self.calls = []
        self.saved = 0

    async def __call__(self, stage, parameters):
        self.calls.append((stage, parameters))
        if stage == self.fail:
            raise RuntimeError("PRIVATE_FAILURE")
        if stage == "next_action":
            if self.saved >= self.steps:
                return _response('{"action":"end","reason_code":"wait_user"}')
            speaker = self.ids[self.saved % len(self.ids)]
            payload = json.loads(parameters['messages'][1]['content'])
            sources = payload['response_sources'][str(speaker)]
            return _response(json.dumps(dict(action='speak', speaker_persona_id=speaker,
                reason_code='follow_up', basis=list(sources)[-1])))
        if stage != 'role_generation':
            raise AssertionError('removed model stage: ' + stage)
        self.saved += 1
        return _response('<reply>' + self.text + '</reply><status emotion="平静" affection_change="2"/>')


class GroupBackgroundFixture:
    setUp = fixtures.GroupOperationFixture.setUp
    group = fixtures.GroupOperationFixture.group

    @contextmanager
    def delayed_budget_clock(self, seconds):
        class Clock:
            now = datetime.utcnow()

            @classmethod
            def utcnow(cls):
                return cls.now

        original = Clock.now
        def delay(connection, cursor, statement, parameters, context, executemany):
            if statement.startswith("UPDATE group_round_operations SET") and "call_count=" in statement:
                # 模拟读取期限之后、预算提交完成之前经过的时间，无需真实等待。
                Clock.now = original + timedelta(seconds=seconds)
        event.listen(self.engine, "before_cursor_execute", delay)
        try:
            with patch.object(checkpoints, "datetime", Clock), patch.object(rounds, "datetime", Clock):
                yield Clock
        finally:
            event.remove(self.engine, "before_cursor_execute", delay)

    def observed(self, sid):
        self.db.expire_all()
        group = self.db.get(Session, sid)
        round_ = operations._latest(sid, self.db)
        candidate = self.db.get(GroupRoundCandidate, round_.selected_candidate_id) if round_ else None
        return dict(observed_round_id=round_.id if round_ else None, observed_candidate_id=candidate.id if candidate else None,
                    observed_candidate_revision=candidate.revision if candidate else None), group.group_revision

    async def submit(self, sid, owner, model, kind="send", request_id=None, **kwargs):
        seen, revision = self.observed(sid)
        if kind == "send":
            kwargs.setdefault("user_content", "hello")
        if kind != "resume":
            kwargs.setdefault("model", "fixture")
        return await background.submit_group_operation(sid, request_id or str(uuid4()), kind, revision, self.db,
            runtime=owner, call_model=model, **seen, **kwargs)

    async def drain(self, owner):
        while owner.tasks:
            await asyncio.gather(*tuple(owner.tasks), return_exceptions=True)
        self.db.expire_all()

    def candidate(self, receipt):
        self.db.expire_all()
        return self.db.get(GroupRoundCandidate, receipt["accepted"]["candidate_id"])
