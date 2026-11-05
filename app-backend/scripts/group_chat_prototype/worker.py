"""单进程临时库原型；正式任务注册、审计与恢复由后续批次接管。"""
import asyncio
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace


def _require_workspace():
    root = Path(__file__).resolve().parents[2]
    marker = os.environ.get("GROUP_PROTOTYPE_WORKER_ROOT")
    if not marker or Path(marker).resolve() != root or Path.cwd().resolve() != root:
        raise RuntimeError("原型只能由隔离启动器执行")
    if (root / ".git").exists() or (root.parent / ".git").exists():
        raise RuntimeError("原型禁止在项目工作区执行")


def _response(raw):
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=raw))])


class ReplayModel:
    def __init__(self, case, member_ids):
        self.case, self.ids = case, member_ids
        self.role_index = 0

    def _visibility(self, slots):
        return json.dumps({"recipients": [{"persona_id": pid, "decision": "visible" if i in slots else "hidden"}
                                         for i, pid in enumerate(self.ids)]})

    async def __call__(self, stage, messages):
        if stage == "user_visibility":
            return _response(self._visibility(self.case["user_visible"]))
        steps = self.case["steps"]
        if stage == "next_action":
            if self.role_index >= len(steps):
                return _response('{"action":"end","reason_code":"wait_user"}')
            return _response(json.dumps({"action": "speak", "speaker_persona_id": self.ids[steps[self.role_index]["speaker"]],
                                         "reason_code": "follow_up"}))
        if stage == "role_generation":
            step = steps[self.role_index]
            return _response('<reply>' + step["content"] + '</reply><status emotion="平静" affection_change="0"/>')
        result = _response(self._visibility(steps[self.role_index]["visible"]))
        self.role_index += 1
        return result


async def _run_round(session_id, user_content, db, runtime, call_model, *, model="fixture-replay", max_steps=4, timeout=300):
    from core.locking import get_session_lock, require_group_runtime
    from services.conversation import group_director_service as director, group_generation_service as generation
    from services.conversation import group_history_service as history
    from services.conversation.group_context_service import build_member_context
    from services.conversation.chat_engine import _prepare_generation_kwargs
    from services.conversation.session_access import SessionKindConflict

    history._require_group(session_id, db)
    history._require_clean_transaction(db)
    require_group_runtime(runtime, db.get_bind())
    if type(max_steps) is not int or not 1 <= max_steps <= 6 or timeout <= 0:
        raise ValueError("原型预算无效")
    lock = get_session_lock(session_id)
    if lock.locked():
        raise SessionKindConflict("群聊正在处理")
    await lock.acquire()
    target = None
    calls = []
    started = time.monotonic()
    # 此参数快照只属于隔离原型，不替代 M3-B 的应用级调用快照。
    director_parameters = None

    async def call(stage, messages, parameters=None, persona_id=None):
        remaining = timeout - (time.monotonic() - started)
        if remaining <= 0 or len(calls) >= 3 * max_steps + 1:
            raise director.GroupDirectorError("call_budget")
        calls.append({"stage": stage, "messages": messages, "speaker_persona_id": persona_id})
        kwargs = {**(parameters or director_parameters), "messages": messages}
        response = await asyncio.wait_for(call_model(stage, kwargs), remaining)
        if time.monotonic() - started >= timeout:
            raise director.GroupDirectorError("call_budget")
        return response.choices[0]

    async def context():
        return await generation._database(director.build_director_context, session_id, db,
            candidate_id=target["candidate_id"] if target else None,
            expected_revision=target["revision"] if target else None)

    try:
        director_parameters = _prepare_generation_kwargs(None, [], model=model)
        scene = await context()
        answer = await call("user_visibility", director.build_director_messages(scene, "user_visibility", user_content=user_content))
        visible = director.parse_visibility(answer.message.content, scene.member_ids, finish_reason=answer.finish_reason)
        try:
            target = await generation._database(history._prepare, session_id, user_content, visible.visible_to, db)
        except generation._DatabaseCancelled as exc:
            if isinstance(exc.result, dict):
                target = exc.result
            raise
        finish_reason = "step_limit"
        for _ in range(max_steps):
            scene = await context()
            if not scene.eligible_ids:
                finish_reason = "no_visible_basis"
                break
            answer = await call("next_action", director.build_director_messages(scene, "next_action"))
            action = director.parse_next_action(answer.message.content, scene.member_ids, scene.eligible_ids,
                                                finish_reason=answer.finish_reason)
            if action.action == "end":
                finish_reason = action.reason_code
                break
            personal = await generation._database(build_member_context, session_id, action.speaker_persona_id,
                target["candidate_id"], target["revision"], db, model=model)
            parameters = json.loads(personal.generation_json)
            answer = await call("role_generation", parameters["messages"], parameters, action.speaker_persona_id)
            if answer.finish_reason not in (None, "stop"):
                raise generation.GroupGenerationError("incomplete_output")
            parsed = generation._parse(answer.message.content, personal)
            proposed = generation.ProposedGroupUtterance(action.speaker_persona_id, parsed[0])
            answer = await call("utterance_visibility", director.build_director_messages(scene, "utterance_visibility", proposed=proposed))
            visible = director.parse_visibility(answer.message.content, scene.member_ids,
                author_id=action.speaker_persona_id, finish_reason=answer.finish_reason)
            try:
                saved = await generation._database(generation._save, session_id, target["candidate_id"], action.speaker_persona_id,
                    target["revision"], parsed, visible.visible_to, db, runtime)
            except generation._DatabaseCancelled as exc:
                if isinstance(exc.result, dict):
                    target["revision"] = exc.result["revision"]
                raise
            target["revision"] = saved["revision"]
        final_scene = await context()
        personal_inputs = {}
        for pid in final_scene.eligible_ids:
            personal = await generation._database(build_member_context, session_id, pid,
                target["candidate_id"], target["revision"], db, model=model)
            personal_inputs[str(pid)] = json.loads(personal.messages_json)
        try:
            done = await generation._database(history._finish, session_id, target["candidate_id"], target["revision"], False, db)
        except generation._DatabaseCancelled as exc:
            if not isinstance(exc.result, dict):
                raise
            # 最终提交已成功时以提交结果为准，返回已完成终态，不再尝试失败转换。
            done = exc.result
        target["revision"] = done["revision"]
        return {**target, "finish_reason": finish_reason, "calls": calls, "error_code": None,
                "personal_inputs": personal_inputs}
    except BaseException as exc:
        if target:
            try:
                await generation._database(generation._fail, session_id, target["candidate_id"], target["revision"], db,
                                           runtime, "cancelled" if isinstance(exc, asyncio.CancelledError) else "prototype_failed")
            except Exception:
                pass
        if isinstance(exc, asyncio.CancelledError):
            raise
        code = exc.code if isinstance(exc, (director.GroupDirectorError, generation.GroupGenerationError)) else (
            "timeout" if isinstance(exc, TimeoutError) else "execution_failed")
        return {**(target or {}), "finish_reason": "failed", "calls": calls, "error_code": code}
    finally:
        lock.release()


async def _run_suite(request):
    from sqlalchemy import event, create_engine
    from sqlalchemy.orm import sessionmaker
    from core.models import Base, Character
    from core.database import get_db
    from application.group_runtime import group_runtime
    from application.factory import create_app
    from fastapi.testclient import TestClient
    from services.conversation.group_session_service import create_group_session, GroupSessionDraft, GroupMember

    engine = create_engine("sqlite:///data/cases.db", connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    sessions = sessionmaker(bind=engine, autoflush=False)
    results = []
    provider = None
    if request["online"]:
        from openai import AsyncOpenAI
        from core.config import settings
        provider = AsyncOpenAI(api_key=settings.CHAT_API_KEY, base_url=settings.CHAT_BASE_URL, max_retries=0, timeout=60)
    try:
        with group_runtime(engine) as runtime:
            Base.metadata.create_all(engine)
            for case in request["cases"]:
                with sessions() as db:
                    cards = [Character(name=name, description="虚构原型角色", first_mes="你好") for name in case["members"]]
                    db.add_all(cards)
                    db.commit()
                    group = await create_group_session(GroupSessionDraft(tuple(GroupMember(card.id) for card in cards),
                        shared_setting=case["setting"]), db)
                    ids = tuple(member["persona_id"] for member in group["members"])
                    replay = ReplayModel(case, ids)
                    async def call_model(stage, kwargs):
                        if provider:
                            return await provider.chat.completions.create(**kwargs)
                        return await replay(stage, kwargs["messages"])
                    result = await _run_round(group["session_id"], case["user"], db, runtime, call_model,
                        model=request["model"], max_steps=case.get("max_steps", 4))
                    app = create_app()
                    app.dependency_overrides[get_db] = lambda: db
                    # 不启动 lifespan；原型自身持有运行权，仅调用只读 HTTP。
                    client = TestClient(app, raise_server_exceptions=True)
                    try:
                        response = client.get(f'/group-sessions/{group["session_id"]}/rounds')
                        response.raise_for_status()
                        rounds = response.json()
                    finally:
                        client.close()
                    checks = {"read_only_http": rounds["total"] == 1,
                              "call_bound": len(result["calls"]) <= 3 * case.get("max_steps", 4) + 1}
                    if not request["online"]:
                        utterances = rounds["rounds"][0]["utterances"] if rounds["rounds"] else []
                        checks["speaker_order"] = [row["speaker_persona_id"] for row in utterances] == [ids[i] for i in case["expected_speakers"]]
                    for expected in case.get("input_checks", []):
                        if request["online"] and expected["present"]:
                            # 在线自然表述不必包含预录响应的标记，语义另由人工审阅。
                            continue
                        text = json.dumps(result.get("personal_inputs", {}).get(str(ids[expected["member"]]), []), ensure_ascii=False)
                        checks[expected["label"]] = (expected["text"] in text) == expected["present"]
                        if not expected["present"]:
                            personal_calls = [call for call in result["calls"] if call["stage"] == "role_generation"
                                              and call["speaker_persona_id"] == ids[expected["member"]]]
                            checks[expected["label"] + "_all_calls"] = all(expected["text"] not in json.dumps(call["messages"], ensure_ascii=False)
                                                                          for call in personal_calls)
                    results.append({"id": case["id"], "member_ids": ids, **result, "http_rounds": rounds,
                        "checks": checks, "granularity_review": "pending" if request["online"] else case.get("granularity_review", "pending")})
    finally:
        if provider:
            await provider.close()
        engine.dispose()
    return results


def main():
    _require_workspace()
    request = json.loads(Path("request.json").read_text(encoding="utf-8"))
    results = asyncio.run(_run_suite(request))
    destination = Path(request["destination"])
    destination.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 1, "mode": "online" if request["online"] else "offline",
              "semantic_review": "pending", "results": results}
    (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(any(result["error_code"] or not all(result["checks"].values()) for result in results))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("隔离原型执行失败，未输出原始服务异常。", file=sys.stderr)
        raise SystemExit(2)
