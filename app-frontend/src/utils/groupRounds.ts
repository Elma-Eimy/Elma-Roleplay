import type { GroupRound } from "../types/groupSessions";

export function groupRoundStatus(round: GroupRound): string {
  return round.confirmed ? "已确认" : round.status === "failed" ? "未完成"
    : round.status === "generating" ? "处理中" : "待确认";
}

export function groupRoundNotice(round: GroupRound): string {
  if (round.status === "failed") {
    return round.error_code === "timeout" ? "本轮等待超时，已保存的发言仍可查看。"
      : "本轮未完成，已保存的发言仍可查看。";
  }
  if (round.status !== "awaiting_confirmation" || round.confirmed) return "";
  switch (round.finish_reason) {
    case "wait_user": return "角色已结束本轮互动，等待下一步安排。";
    case "no_visible_basis": return "没有成员获得可用内容，本轮未生成角色发言。";
    case "step_limit": return "已达到本轮发言上限，互动已停止。";
    default: return "";
  }
}
