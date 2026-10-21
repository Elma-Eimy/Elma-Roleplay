import { request, USE_MOCK } from "./config";
import * as mock from "./mock/sessions";
import type {
  SessionDetail,
  CreateSessionParams,
  CreateSessionResponse,
  GetSessionsResponse,
  GetRecentSessionsResponse,
  UpdateTitleResponse,
  DeleteSessionResponse,
  TriggerCognitionResponse,
} from "../types/sessions";

/**
 * 创建新会话（全新会话或继承自父会话的分支会话）。
 * POST /sessions/create
 */
export async function createSession(
  params: CreateSessionParams
): Promise<CreateSessionResponse> {
  if (USE_MOCK) return mock.createSession(params);

  return request<CreateSessionResponse>("/sessions/create", {
    method: "POST",
    body: JSON.stringify(params),
  });
}

/**
 * 列出指定角色的所有会话。
 * GET /sessions?character_id={characterId}
 */
export async function getSessions(
  characterId: number,
  limit = 50,
  offset = 0,
  includeLastMessage = true
): Promise<GetSessionsResponse> {
  if (USE_MOCK) return mock.getSessions(characterId, limit, offset, includeLastMessage);

  return request<GetSessionsResponse>(
    `/sessions?character_id=${characterId}&include_last_message=${includeLastMessage}&limit=${limit}&offset=${offset}`
  );
}

/**
 * 获取指定角色的全部会话页，供故事树等需要完整分支关系的界面使用。
 */
export async function getAllSessions(
  characterId: number,
  includeLastMessage = true
): Promise<GetSessionsResponse> {
  const pageSize = 100;
  let page = await getSessions(characterId, pageSize, 0, includeLastMessage);
  const sessions = [...page.sessions];
  let nextOffset = page.offset + page.sessions.length;

  while (page.has_more) {
    page = await getSessions(characterId, pageSize, nextOffset, includeLastMessage);
    sessions.push(...page.sessions);
    nextOffset = page.offset + page.sessions.length;
  }

  return {
    character_id: characterId,
    sessions,
    total: page.total,
    limit: sessions.length,
    offset: 0,
    has_more: false,
  };
}

/**
 * 获取首页最近会话聚合数据。
 * 后端应在一次查询中返回角色摘要与最后一条消息，避免首页 N+1 请求。
 * GET /sessions/recent?limit={limit}&offset={offset}
 */
export async function getRecentSessions(
  limit = 50,
  offset = 0
): Promise<GetRecentSessionsResponse> {
  if (USE_MOCK) return mock.getRecentSessions(limit, offset);

  return request<GetRecentSessionsResponse>(
    `/sessions/recent?limit=${limit}&offset=${offset}`
  );
}

/**
 * 获取指定会话的详细信息（包含人设状态数据）。
 * GET /sessions/{session_id}
 */
export async function getSession(sessionId: number): Promise<SessionDetail> {
  if (USE_MOCK) return mock.getSession(sessionId);

  return request<SessionDetail>(`/sessions/${sessionId}`);
}

/**
 * 重命名会话的标题。
 * PUT /sessions/{session_id}/title
 */
export async function updateSessionTitle(
  sessionId: number,
  title: string
): Promise<UpdateTitleResponse> {
  if (USE_MOCK) return mock.updateSessionTitle(sessionId, title);

  return request<UpdateTitleResponse>(`/sessions/${sessionId}/title`, {
    method: "PUT",
    body: JSON.stringify({ title }),
  });
}

/**
 * 删除会话并安全地重联其子分支会话。
 * DELETE /sessions/{session_id} -> 改为 POST /sessions/{session_id}/delete 避开移动端及网关 DELETE 限制
 */
export async function deleteSession(
  sessionId: number
): Promise<DeleteSessionResponse> {
  if (USE_MOCK) return mock.deleteSession(sessionId);

  return request<DeleteSessionResponse>(`/sessions/${sessionId}/delete`, {
    method: "POST",
  });
}

/**
 * 手动触发更新角色微观认知状态。
 * POST /sessions/{session_id}/trigger_cognition
 */
export async function triggerCognition(
  sessionId: number
): Promise<TriggerCognitionResponse> {
  if (USE_MOCK) return mock.triggerCognition(sessionId);

  return request<TriggerCognitionResponse>(
    `/sessions/${sessionId}/trigger_cognition`,
    { method: "POST" }
  );
}

// Compatibility exports for existing callers; new code should import its domain directly.
export * from "./messages";
export * from "./memories";
export * from "./prompts";
export type {
  PersonaSummary,
  PersonaDetail,
  CharacterRef,
  SessionSummary,
  SessionDetail,
  CreateSessionParams,
  CreateSessionResponse,
  GetSessionsResponse,
  RecentSessionSummary,
  GetRecentSessionsResponse,
  UpdateTitleResponse,
  DeleteSessionResponse,
  TriggerCognitionResponse,
} from "../types/sessions";
export type {
  MessageCandidate,
  Message,
  GetHistoryResponse,
  UpdateMessageResponse,
  DeleteMessageResponse,
  SwitchCandidateResponse,
} from "../types/messages";
export type {
  MemoryChunk,
  MemoryScope,
  MemoryStatus,
  MemoryStats,
  GetSessionMemoriesParams,
  GetSessionMemoriesResponse,
  CharacterMemoryOverviewSession,
  CharacterMemoryOverviewResponse,
  TriggerSummaryResponse,
  MemoryCreateResponse,
  MemoryUpdateResponse,
  MemoryDeleteResponse,
} from "../types/memories";
export type {
  TokenEstimateDetail,
  TokenEstimate,
  CompiledPromptResponse,
} from "../types/prompts";
