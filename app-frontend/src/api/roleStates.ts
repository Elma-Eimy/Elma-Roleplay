import { request, USE_MOCK } from "./config";
import type { RoleStatePatch, RoleStateSnapshot } from "@/types/roleState";

export async function getRoleState(sessionId: number): Promise<RoleStateSnapshot> {
  if (USE_MOCK) throw new Error("离线模式暂不支持角色状态，请连接后端使用。");
  return request<RoleStateSnapshot>(`/sessions/${sessionId}/role-state`);
}

export async function updateRoleState(sessionId: number, expectedRevision: string, patch: RoleStatePatch): Promise<RoleStateSnapshot> {
  if (USE_MOCK) throw new Error("离线模式暂不支持修改角色状态，请连接后端使用。");
  return request<RoleStateSnapshot>(`/sessions/${sessionId}/role-state`, {
    method: "PUT",
    body: JSON.stringify({ expected_revision: expectedRevision, patch }),
  });
}
