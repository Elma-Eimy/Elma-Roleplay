"""群聊 M4 接受事务；后台执行通过持权包装接入。"""
import hashlib
import json
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, text

from core.models import GroupMemberInsight, GroupRecallCard, GroupRound, GroupRoundCandidate, GroupRoundOperation, GroupContentItem
from services.conversation import group_history_service as history
from services.conversation.group_session_service import _begin_write, _locked_write, GroupSessionValidationError
from services.conversation.session_access import group_session_operation, SessionKindConflict
from services.conversation.group_call_snapshot import persist_group_calls, validate_group_call_selection


def _active(session_id, db):
    return db.query(GroupRoundOperation).filter(GroupRoundOperation.session_id == session_id,
        GroupRoundOperation.status.in_(("queued", "running"))).first() is not None


def _latest(session_id, db):
    return db.query(GroupRound).filter_by(session_id=session_id, discarded_at=None).order_by(
        GroupRound.round_index.desc()).first()


def _observed(group, latest, expected, db):
    revision, round_id, candidate_id, candidate_revision = expected
    history._positive(revision, "会话版本", 0)
    if group.group_revision != revision or _active(group.id, db):
        raise SessionKindConflict("会话版本已变化或存在活动操作")
    candidate = db.get(GroupRoundCandidate, latest.selected_candidate_id) if latest else None
    actual = (latest.id if latest else None, candidate.id if candidate else None,
              candidate.revision if candidate else None)
    if actual != (round_id, candidate_id, candidate_revision):
        raise SessionKindConflict("所见轮次或候选已变化")
    if candidate and candidate.status == "generating":
        raise SessionKindConflict("候选正在执行")
    return candidate


def _receipt(operation):
    # 回执只表达接受时的结果，不能用它覆盖当前选择。
    return {"operation_id": operation.id, "status": operation.status,
            "accepted": json.loads(operation.accepted_result_json)}


@group_session_operation
async def accept_group_operation(session_id, client_request_id, kind, expected_group_revision,
                                 db, *, observed_round_id=None, observed_candidate_id=None,
                                 observed_candidate_revision=None, user_content=None,
                                 target_candidate_id=None, target_candidate_revision=None,
                                 model=None, thinking_mode=None, reasoning_effort=None,
                                 call_snapshot=None, max_steps=4, round_id=None):
    """内部事务原语，不派发模型；运行入口使用后台握手服务。"""
    history._require_group(session_id, db)
    history._require_clean_transaction(db)
    request_id, request, fingerprint = _command(client_request_id, kind, expected_group_revision,
        observed_round_id=observed_round_id, observed_candidate_id=observed_candidate_id,
        observed_candidate_revision=observed_candidate_revision, user_content=user_content,
        target_candidate_id=target_candidate_id, target_candidate_revision=target_candidate_revision,
        model=model, thinking_mode=thinking_mode, reasoning_effort=reasoning_effort, max_steps=max_steps, round_id=round_id)
    previous = _existing(session_id, request_id, fingerprint, db)
    if previous is not None:
        return previous
    return await _locked_write([session_id], _accept, session_id, request_id, request,
                               fingerprint, call_snapshot, db)


def _command(client_request_id, kind, expected_group_revision, *, observed_round_id=None,
             observed_candidate_id=None, observed_candidate_revision=None, user_content=None,
             target_candidate_id=None, target_candidate_revision=None, model=None, thinking_mode=None,
             reasoning_effort=None, max_steps=4, round_id=None, http_resources=False):
    try:
        request_id = str(UUID(client_request_id))
    except (ValueError, TypeError, AttributeError):
        raise GroupSessionValidationError("请求 ID 必须是 UUID") from None
    if kind not in ("send", "regenerate", "resume", "select", "discard"):
        raise GroupSessionValidationError("当前批次不支持该操作")
    history._positive(expected_group_revision, "会话版本", 0)
    for value in (round_id, observed_round_id, observed_candidate_id, target_candidate_id):
        if value is not None:
            history._positive(value, "资源 ID")
    for value in (observed_candidate_revision, target_candidate_revision):
        if value is not None:
            history._positive(value, "候选版本", 0)
    history._positive(max_steps, "成功步数")
    if max_steps > 6:
        raise GroupSessionValidationError("成功步数不能超过 6")
    if kind in ("send", "regenerate"):
        if kind == "send" and (not isinstance(user_content, str) or not user_content.strip()):
            raise GroupSessionValidationError("用户输入不能为空")
        if kind == "send" and (target_candidate_id is not None or target_candidate_revision is not None):
            raise GroupSessionValidationError("发送不能指定目标候选")
        if kind == "regenerate" and (user_content is not None or target_candidate_id is not None or target_candidate_revision is not None):
            raise GroupSessionValidationError("重生成不能重传原文或指定候选")
        if model is not None:
            if not isinstance(model, str) or not model.strip():
                raise GroupSessionValidationError("模型 ID 不能为空")
            model = model.strip()
        if thinking_mode not in (None, "inherit", "enabled", "disabled"):
            raise GroupSessionValidationError("思考模式无效")
        if reasoning_effort is not None and (not isinstance(reasoning_effort, str) or not reasoning_effort):
            raise GroupSessionValidationError("思考强度无效")
        thinking_mode = None if thinking_mode == "inherit" else thinking_mode
        reasoning_effort = None if reasoning_effort == "inherit" else reasoning_effort
    elif user_content is not None or any(value is not None for value in (model, thinking_mode, reasoning_effort)):
        raise GroupSessionValidationError("选择和撤回不能携带生成参数")
    if kind in ("select", "resume") and (target_candidate_id is None or target_candidate_revision is None):
        raise GroupSessionValidationError("选择需要目标候选及版本")
    if kind == "discard" and (target_candidate_id is not None or target_candidate_revision is not None):
        raise GroupSessionValidationError("撤回不能指定目标候选")
    expected = (expected_group_revision, observed_round_id, observed_candidate_id, observed_candidate_revision)
    request = dict(kind=kind, expected=expected, user_content=user_content,
                   target_candidate_id=target_candidate_id, target_candidate_revision=target_candidate_revision,
                   model=model, thinking_mode=thinking_mode, reasoning_effort=reasoning_effort, max_steps=max_steps)
    if round_id is not None:
        request["round_id"] = round_id
    fingerprint = hashlib.sha256(json.dumps(request, ensure_ascii=False, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()
    if http_resources:
        request["_http_resources"] = True
    return request_id, request, fingerprint


def _existing(session_id, request_id, fingerprint, db):
    # 执行任务可能仍持有会话锁；已提交回执的重放不能因此变成新操作。
    db.rollback()
    db.expire_all()
    previous = db.query(GroupRoundOperation).filter_by(session_id=session_id, client_request_id=request_id).first()
    if previous:
        try:
            if previous.request_fingerprint != fingerprint:
                raise SessionKindConflict("请求 ID 已用于不同操作")
            return _receipt(previous)
        finally:
            db.rollback()
    return None


def _accept(session_id, request_id, request, fingerprint, snapshot, db, with_created=False):
    try:
        _begin_write(db)
        group = history._require_group(session_id, db)
        previous = db.query(GroupRoundOperation).filter_by(session_id=session_id, client_request_id=request_id).first()
        if previous:
            if previous.request_fingerprint != fingerprint:
                raise SessionKindConflict("请求 ID 已用于不同操作")
            result = _receipt(previous)
            db.rollback()
            return (result, False) if with_created else result
        _resources(session_id, request, db)
        latest = _latest(session_id, db)
        selected = _observed(group, latest, request["expected"], db)
        kind = request["kind"]
        now = datetime.utcnow()
        if kind in ("send", "regenerate"):
            from services.media.group_portraits import _freeze_current_choices
            portrait_snapshot = _freeze_current_choices(session_id, db)
            # 幂等命中不重新解析服务器默认参数；首次接受必须保存可靠快照。
            encoded, provider = persist_group_calls(snapshot, request["max_steps"], history._members(session_id, db))
            validate_group_call_selection(encoded, model=request["model"], thinking_mode=request["thinking_mode"],
                                          reasoning_effort=request["reasoning_effort"])
            if kind == "send":
                if latest and latest.confirmed_at is None:
                    if not selected or selected.status != "awaiting_confirmation":
                        raise SessionKindConflict("当前轮次尚未完整成功")
                    from services.memory.group_memory_capture import enqueue_confirmed_group
                    latest.confirmed_at = now
                    enqueue_confirmed_group(latest, selected, db)
                    db.flush()
                index = (db.query(func.max(GroupRound.round_index)).filter_by(session_id=session_id).scalar() or 0) + 1
                latest = GroupRound(session_id=session_id, round_index=index, user_content=request["user_content"])
                db.add(latest)
                db.flush()
                version = 1
            else:
                if not latest or latest.confirmed_at is not None:
                    raise SessionKindConflict("只能重生成最新未确认轮次")
                version = db.query(func.max(GroupRoundCandidate.version)).filter_by(round_id=latest.id).scalar() + 1
            if snapshot.inherited_recall:
                policy = json.loads(encoded)
                policy["group_card_limit"] = db.query(func.max(GroupRecallCard.id)).scalar() or 0
                encoded = json.dumps(policy, ensure_ascii=False, sort_keys=True)
            selected = GroupRoundCandidate(session_id=session_id, round_id=latest.id, protocol_version=2, version=version,
                portrait_selections_json=portrait_snapshot,
                insight_watermark=db.query(func.max(GroupMemberInsight.id)).scalar() or 0,
                checkpoint="user_visibility", call_snapshot_json=encoded, provider_fingerprint=provider)
            db.add(selected)
            db.flush()
            if kind == "send":
                latest.selected_candidate_id = selected.id
            db.add(GroupContentItem(session_id=session_id, candidate_id=selected.id, sequence=0, kind="user"))
        else:
            if not latest or latest.confirmed_at is not None or not selected:
                raise SessionKindConflict("只能操作最新未确认轮次")
            if kind == "resume":
                from services.conversation.group_checkpoint_service import validate_prefix
                from services.conversation.group_call_snapshot import restore_group_calls
                target = db.get(GroupRoundCandidate, request["target_candidate_id"])
                if (not target or target.session_id != session_id or target.round_id != latest.id
                        or target.status != "failed" or target.revision != request["target_candidate_revision"]):
                    raise SessionKindConflict("续接目标或版本无效")
                snapshot, max_steps = restore_group_calls(target, history._members(session_id, db))
                from services.conversation.group_call_snapshot import require_executable_calls
                require_executable_calls(snapshot)
                validate_prefix(latest, target, db)
                from services.conversation.group_checkpoint_service import saved_steps
                remaining = max_steps - saved_steps(target.id, db)
                if remaining < 0 or (target.checkpoint == "finish") != (remaining == 0):
                    raise SessionKindConflict("候选成功步数超限")
                target.status = "generating"
                target.error_code = None
                target.revision += 1
                selected = target
            elif kind == "select":
                target = db.get(GroupRoundCandidate, request["target_candidate_id"])
                if not target or target.session_id != session_id or target.round_id != latest.id:
                    raise SessionKindConflict("目标候选不属于当前轮次")
                if target.status != "awaiting_confirmation" or target.revision != request["target_candidate_revision"]:
                    raise SessionKindConflict("目标候选未成功或版本已变化")
                selected = target
                latest.selected_candidate_id = target.id
            else:
                latest.discarded_at = now
        group.group_revision += 1
        accepted = dict(round_id=latest.id, candidate_id=selected.id, group_revision=group.group_revision,
                        candidate_revision=selected.revision, kind=kind)
        operation = GroupRoundOperation(session_id=session_id, round_id=latest.id, candidate_id=selected.id,
            client_request_id=request_id, kind=kind, status="queued" if kind in ("send", "regenerate", "resume") else "succeeded",
            request_fingerprint=fingerprint, accepted_result_json=json.dumps(accepted),
            call_limit=(2 * request["max_steps"] + 1 if kind in ("send", "regenerate") else
                        2 * remaining + 1 if kind == "resume" and remaining else 0),
            finished_at=None if kind in ("send", "regenerate", "resume") else now)
        db.add(operation)
        db.flush()
        result = _receipt(operation)
        db.commit()
        return (result, True) if with_created else result
    except BaseException:
        db.rollback()
        raise


def _resources(session_id, request, db):
    """HTTP 路径与嵌套资源在接受事务内核对；重放回执优先于当前资源状态。"""
    from services.conversation.group_session_service import GroupSessionNotFound
    if not request.get("_http_resources") and "round_id" not in request:
        return
    seen_round, seen_candidate = request["expected"][1:3]
    for rid in (request.get("round_id"), seen_round):
        if rid is not None:
            row = db.get(GroupRound, rid)
            if row is None or row.session_id != session_id:
                raise GroupSessionNotFound("轮次不属于本群或不存在")
    for cid in (seen_candidate, request["target_candidate_id"]):
        if cid is not None:
            row = db.get(GroupRoundCandidate, cid)
            if row is None or row.session_id != session_id or row.round_id != seen_round:
                raise GroupSessionNotFound("候选不属于本群本轮或不存在")
    if request.get("round_id") is not None and request["round_id"] != seen_round:
        raise SessionKindConflict("路径轮次与所见轮次不一致")


@group_session_operation
def get_group_operation_capabilities(session_id, db):
    """内部能力判定；HTTP 生成仍关闭，旧失败候选不伪造续接参数。"""
    history._require_group(session_id, db)
    history._require_clean_transaction(db)
    db.rollback()
    db.expire_all()
    db.execute(text("BEGIN"))
    try:
        group = history._require_group(session_id, db)
        latest = _latest(session_id, db)
        candidate = db.get(GroupRoundCandidate, latest.selected_candidate_id) if latest else None
        idle = not _active(session_id, db) and (not candidate or candidate.status != "generating")
        pending = bool(latest and latest.confirmed_at is None)
        return dict(group_revision=group.group_revision, can_generate=False,
                    can_accept=bool(idle and (not pending or candidate and candidate.status == "awaiting_confirmation")),
                    can_select=idle and pending, can_discard=idle and pending)
    finally:
        db.rollback()
