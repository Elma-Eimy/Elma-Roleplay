import type { GroupRound } from "../types/groupSessions";

export function groupRoundStatus(round: GroupRound): string {
  return round.confirmed ? "已确认" : round.status === "failed" ? "未完成"
    : round.status === "generating" ? "处理中" : "待确认";
}

export function groupRoundNotice(round: GroupRound): string {
  if (round.status === "failed") {
    const reason = ({ timeout: '本轮等待超时', incomplete_output: '模型输出被截断，本轮未完成',
      invalid_output: '模型回复格式校验未通过，本轮未完成',
      experience_check_failed: '角色亲历审查未完成，本轮未完成',
      unsupported_experience: '回复含缺乏依据的亲历表述，本轮未完成' } as Record<string, string>)[round.error_code || ''];
    return `${reason || '本轮未完成'}，已保存的发言仍可查看。`;
  }
  if (round.status !== "awaiting_confirmation" || round.confirmed) return "";
  switch (round.finish_reason) {
    case "wait_user": return "";
    case "no_visible_basis": return "没有成员获得可用内容，本轮未生成角色发言。";
    case "step_limit": return "已到本轮发言上限，回复已保存。";
    default: return "";
  }
}
