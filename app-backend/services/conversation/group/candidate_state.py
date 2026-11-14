"""候选状态转换规则；调用方负责归属、版本校验及事务提交。"""
import json

from services.conversation.session_access import SessionKindConflict


def _generating(candidate, checkpoints=None):
    if candidate.status != "generating" or (checkpoints is not None and candidate.checkpoint not in checkpoints):
        raise SessionKindConflict("候选状态或检查点已变化")


def user_saved(candidate):
    _generating(candidate, ("user_visibility",))
    candidate.checkpoint = "next_action"
    candidate.revision += 1


def action_saved(candidate, *, persistent):
    _generating(candidate, ("next_action",) if persistent else None)
    if persistent:
        candidate.checkpoint = "role_generation"
    candidate.revision += 1


def utterance_saved(candidate, *, completed_steps=None):
    _generating(candidate, ("role_generation",) if completed_steps is not None else None)
    if completed_steps is not None:
        policy = json.loads(candidate.call_snapshot_json)
        candidate.checkpoint = ("next_action" if policy.get("director_ending")
                                else "finish" if completed_steps >= policy["max_steps"] else "next_action")
    candidate.revision += 1


def prepare_finish(candidate, reason):
    _generating(candidate, ("next_action",))
    if reason not in ("wait_user", "no_visible_basis"):
        raise SessionKindConflict("不能保存当前结束决定")
    candidate.checkpoint = "finish"
    candidate.finish_reason = reason
    candidate.revision += 1


def finish(candidate, reason, *, persistent=False):
    _generating(candidate, ("next_action", "finish") if persistent else None)
    if persistent:
        candidate.checkpoint = "done"
    candidate.status = "awaiting_confirmation"
    candidate.finish_reason = reason
    candidate.error_code = None
    candidate.revision += 1


def fail(candidate, code, *, preserve_finish=False):
    _generating(candidate)
    candidate.status = "failed"
    candidate.error_code = code
    # 后台续接依赖已保存的导演结束决定；内部单步失败沿用原有清理规则。
    if not preserve_finish:
        candidate.finish_reason = None
    candidate.revision += 1


def resume(candidate):
    if candidate.status != "failed":
        raise SessionKindConflict("只能续接失败候选")
    candidate.status = "generating"
    candidate.error_code = None
    candidate.revision += 1
