"""只序列化已接受的结构化决定，不接收原始模型文本。"""
import json

from sqlalchemy import func

from core.models import GroupDirectorStep, SessionPersona
from services.conversation.group_unit_protocol import UnitPlan


def record(candidate, stage, decision, model, db, *, item=None):
    speaker, reason = None, None
    if stage in ("user_visibility", "utterance_visibility"):
        if not isinstance(decision, UnitPlan) or item is None:
            raise ValueError("审计缺少已校验单元")
        members = {row[0] for row in db.query(SessionPersona.id).filter_by(session_id=candidate.session_id)}
        payload = decision.decision(members)
        speaker = item.speaker_persona_id
    elif stage == "next_action":
        if decision.action != "speak" or decision.reason_code not in ("direct_response", "follow_up"):
            raise ValueError("审计调度无效")
        speaker, reason = decision.speaker_persona_id, decision.reason_code
        payload = {"action": "speak", "speaker_persona_id": speaker, "reason_code": reason}
        if decision.basis is not None:
            payload["basis"] = decision.basis
    elif stage == "finish" and decision in ("wait_user", "step_limit", "no_visible_basis"):
        reason = decision
        payload = {"action": "end", "reason_code": reason}
    else:
        raise ValueError("审计阶段无效")
    if not isinstance(model, str) or not 1 <= len(model) <= 200:
        raise ValueError("审计模型名无效")
    index = (db.query(func.max(GroupDirectorStep.step_index)).filter_by(candidate_id=candidate.id).scalar() or 0) + 1
    db.add(GroupDirectorStep(candidate_id=candidate.id, session_id=candidate.session_id, stage=stage, step_index=index,
        expected_revision=candidate.revision, result_revision=candidate.revision + 1,
        speaker_persona_id=speaker, item_id=item.id if item else None,
        decision_json=json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        reason_code=reason, model=model, policy_version=candidate.protocol_version))
