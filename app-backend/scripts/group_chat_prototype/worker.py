"""单进程临时库原型；正式任务注册、审计与恢复由后续批次接管。"""
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
    from services.conversation.group_round_service import run_group_round
    return await run_group_round(session_id, user_content, db, runtime=runtime, call_model=call_model,
                                 model=model, max_steps=max_steps, timeout=timeout, collect_inputs=True)


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
                              "input_collection": result.get("error_code") is None and result.get("diagnostic_error_code") is None,
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
