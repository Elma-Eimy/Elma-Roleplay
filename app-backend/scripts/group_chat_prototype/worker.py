"""单进程临时库原型；复用内部整轮和审计，不开放候选恢复。"""
import asyncio
import json
import os
from pathlib import Path
import sys
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

    async def __call__(self, stage, messages):
        steps = self.case['steps']
        if self.case.get('fail_at') == stage and self.role_index == self.case.get('fail_step', 0):
            return _response('')
        if stage == 'next_action':
            if self.role_index >= len(steps):
                return _response('{"action":"end","reason_code":"wait_user"}')
            step = steps[self.role_index]
            speaker = self.ids[step['speaker']]
            payload = json.loads(messages[1]['content'])
            sources = payload['response_sources'][str(speaker)]
            choices = list(sources)
            if 'reply_to_step' in step:
                utterances = [row for row in payload['history'] if row['kind'] == 'utterance']
                basis = utterances[step['reply_to_step']]['reference']
            else:
                basis = choices[-1]
            return _response(json.dumps(dict(action='speak', speaker_persona_id=speaker,
                reason_code='follow_up', basis=basis)))
        if stage != 'role_generation':
            raise AssertionError('unsupported model stage: ' + stage)
        text = steps[self.role_index]['content']
        self.role_index += 1
        return _response('<reply>' + text + '</reply><status emotion="平静" affection_change="0"/>')


async def _run_round(session_id, user_content, db, runtime, call_model, *, model="fixture-replay", max_steps=4, timeout=300):
    from services.conversation.group.round_service import run_group_round
    return await run_group_round(session_id, user_content, db, runtime=runtime, call_model=call_model,
                                 model=model, max_steps=max_steps, timeout=timeout, collect_inputs=True,
                                 protocol_version=2)


async def _run_suite(request):
    from sqlalchemy import event, create_engine
    from sqlalchemy.orm import sessionmaker
    from core.models import Base, Character, GroupDirectorStep, GroupRoundCandidate
    from core.database import get_db
    from application.group_runtime import group_runtime
    from application.factory import create_app
    from fastapi.testclient import TestClient
    from services.conversation.group.session_service import create_group_session, GroupSessionDraft, GroupMember
    from services.conversation.group.call_snapshot import DIRECTOR_CALL_LIMIT

    engine = create_engine("sqlite:///data/cases.db", connect_args={"check_same_thread": False})
    @event.listens_for(engine, "connect")
    def foreign_keys(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
    sessions = sessionmaker(bind=engine, autoflush=False)
    results = []
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
                        return await replay(stage, kwargs["messages"])
                    result = await _run_round(group["session_id"], case["user"], db, runtime, None if request["online"] else call_model,
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
                              "call_bound": len(result["calls"]) <= DIRECTOR_CALL_LIMIT}
                    if case.get("expected_error") is None:
                        checks["input_collection"] = result.get("error_code") is None and result.get("diagnostic_error_code") is None
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
                    saved_candidate = db.get(GroupRoundCandidate, result.get("candidate_id")) if result.get("candidate_id") else None
                    steps = db.query(GroupDirectorStep).filter_by(candidate_id=result.get("candidate_id")).order_by(
                        GroupDirectorStep.step_index).all() if saved_candidate else []
                    audit_rows = [{"stage": row.stage, "step_index": row.step_index,
                        "expected_revision": row.expected_revision, "result_revision": row.result_revision,
                        "speaker_persona_id": row.speaker_persona_id, "item_id": row.item_id,
                        "decision": json.loads(row.decision_json), "reason_code": row.reason_code,
                        "model": row.model, "policy_version": row.policy_version} for row in steps]
                    candidate_state = ({"protocol_version": saved_candidate.protocol_version,
                        "revision": saved_candidate.revision, "status": saved_candidate.status,
                        "finish_reason": saved_candidate.finish_reason, "error_code": saved_candidate.error_code}
                        if saved_candidate else None)
                    checks["candidate_handoff"] = bool(saved_candidate and rounds["rounds"]
                        and rounds["rounds"][0]["candidate_id"] == result["candidate_id"]
                        and rounds["rounds"][0]["revision"] == saved_candidate.revision == result["revision"]
                        and rounds["rounds"][0]["finish_reason"] == saved_candidate.finish_reason
                        and rounds["rounds"][0]["error_code"] == saved_candidate.error_code
                        and rounds["rounds"][0]["status"] == saved_candidate.status)
                    checks["expected_outcome"] = result.get("error_code") == case.get("expected_error")
                    results.append({"id": case["id"], "session_id": group["session_id"], "member_ids": ids,
                        **result, "http_rounds": rounds,
                        "candidate_state": candidate_state, "director_steps": audit_rows,
                        "checks": checks, "granularity_review": "pending" if request["online"] else case.get("granularity_review", "pending")})
    finally:
        engine.dispose()
    return results


def main():
    _require_workspace()
    request = json.loads(Path("request.json").read_text(encoding="utf-8"))
    results = asyncio.run(_run_suite(request))
    destination = Path(request["destination"])
    destination.mkdir(parents=True, exist_ok=False)
    report = {"schema_version": 2, "mode": "online" if request["online"] else "offline",
              "semantic_review": "pending", "results": results}
    (destination / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    if request.get("serve"):
        from scripts.group_chat_prototype.preview import serve_preview
        serve_preview(Path("data/cases.db"), report, request["port"], request["preview_seconds"],
                      Path("h5") if request.get("frontend_dist") else None)
    return int(any(not all(result["checks"].values()) for result in results))


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception:
        print("隔离原型执行失败，未输出原始服务异常。", file=sys.stderr)
        raise SystemExit(2)
