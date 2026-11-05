import { request, USE_MOCK } from "./config";
import * as mock from "./mock/groupSessions";
import type {
  CreateGroupSessionParams,
  GroupSessionDetail,
  GetGroupSessionsResponse,
  DeleteGroupSessionResponse,
  GetGroupRoundsResponse,
  SendGroupRoundParams, RegenerateGroupRoundParams, GroupRoundCommand, GroupCandidateCommand,
  GroupAcceptedOperation, GetGroupRequestResponse, GetGroupCandidatesResponse, GetGroupCandidateResponse,
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

export async function getGroupRounds(sessionId: number, limit = 20, offset = 0): Promise<GetGroupRoundsResponse> {
  if (USE_MOCK) return mock.getGroupRounds(sessionId, limit, offset);
  return request<GetGroupRoundsResponse>(`/group-sessions/${sessionId}/rounds?limit=${limit}&offset=${offset}`);
}

export async function sendGroupRound(sessionId: number, params: SendGroupRoundParams): Promise<GroupAcceptedOperation> {
  if (USE_MOCK) return mock.unsupportedGroupOperation(sessionId);
  return request(`/group-sessions/${sessionId}/rounds`, { method: "POST", body: JSON.stringify(params) });
}

export async function regenerateGroupRound(sessionId: number, roundId: number, params: RegenerateGroupRoundParams): Promise<GroupAcceptedOperation> {
  if (USE_MOCK) return mock.unsupportedGroupOperation(sessionId);
  return request(`/group-sessions/${sessionId}/rounds/${roundId}/regenerate`, { method: "POST", body: JSON.stringify(params) });
}

export async function resumeGroupRound(sessionId: number, roundId: number, params: GroupCandidateCommand): Promise<GroupAcceptedOperation> {
  if (USE_MOCK) return mock.unsupportedGroupOperation(sessionId);
  return request(`/group-sessions/${sessionId}/rounds/${roundId}/resume`, { method: "POST", body: JSON.stringify(params) });
}

export async function selectGroupCandidate(sessionId: number, roundId: number, params: GroupCandidateCommand): Promise<GroupAcceptedOperation> {
  if (USE_MOCK) return mock.unsupportedGroupOperation(sessionId);
  return request(`/group-sessions/${sessionId}/rounds/${roundId}/select-candidate`, { method: "POST", body: JSON.stringify(params) });
}

export async function discardGroupRound(sessionId: number, roundId: number, params: GroupRoundCommand): Promise<GroupAcceptedOperation> {
  if (USE_MOCK) return mock.unsupportedGroupOperation(sessionId);
  return request(`/group-sessions/${sessionId}/rounds/${roundId}/discard`, { method: "POST", body: JSON.stringify(params) });
}

export async function getGroupRequest(sessionId: number, requestId: string): Promise<GetGroupRequestResponse> {
  if (USE_MOCK) return mock.unsupportedGroupOperation(sessionId);
  return request(`/group-sessions/${sessionId}/requests/${encodeURIComponent(requestId)}`);
}

export async function getGroupCandidates(sessionId: number, roundId: number, limit = 20, offset = 0): Promise<GetGroupCandidatesResponse> {
  if (USE_MOCK) return mock.unsupportedGroupOperation(sessionId);
  return request(`/group-sessions/${sessionId}/rounds/${roundId}/candidates?limit=${limit}&offset=${offset}`);
}

export async function getGroupCandidate(sessionId: number, roundId: number, candidateId: number): Promise<GetGroupCandidateResponse> {
  if (USE_MOCK) return mock.unsupportedGroupOperation(sessionId);
  return request(`/group-sessions/${sessionId}/rounds/${roundId}/candidates/${candidateId}`);
}
