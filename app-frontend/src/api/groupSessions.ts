import { request, USE_MOCK } from "./config";
import * as mock from "./mock/groupSessions";
import type {
  CreateGroupSessionParams,
  GroupSessionDetail,
  GetGroupSessionsResponse,
  DeleteGroupSessionResponse,
} from "../types/groupSessions";

export async function createGroupSession(params: CreateGroupSessionParams): Promise<GroupSessionDetail> {
  if (USE_MOCK) return mock.createGroupSession(params);
  return request<GroupSessionDetail>("/group-sessions", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

export async function getGroupSessions(limit = 20, offset = 0): Promise<GetGroupSessionsResponse> {
  if (USE_MOCK) return mock.getGroupSessions(limit, offset);
  return request<GetGroupSessionsResponse>(`/group-sessions?limit=${limit}&offset=${offset}`);
}

export async function getGroupSession(sessionId: number): Promise<GroupSessionDetail> {
  if (USE_MOCK) return mock.getGroupSession(sessionId);
  return request<GroupSessionDetail>(`/group-sessions/${sessionId}`);
}

export async function deleteGroupSession(sessionId: number): Promise<DeleteGroupSessionResponse> {
  if (USE_MOCK) return mock.deleteGroupSession(sessionId);
  return request<DeleteGroupSessionResponse>(`/group-sessions/${sessionId}/delete`, { method: "POST" });
}
