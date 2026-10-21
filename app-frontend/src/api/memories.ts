import { request, USE_MOCK } from "./config";
import * as mock from "./mock/memories";
import type {
  GetSessionMemoriesParams,
  GetSessionMemoriesResponse,
  CharacterMemoryOverviewResponse,
  TriggerSummaryResponse,
  MemoryCreateResponse,
  MemoryUpdateResponse,
  MemoryDeleteResponse,
} from "../types/memories";

/**
 * 手动触发新消息的记忆提纯（记忆元提取）。
 * POST /sessions/{session_id}/trigger_summary
 */
export async function triggerSummary(
  sessionId: number
): Promise<TriggerSummaryResponse> {
  if (USE_MOCK) return mock.triggerSummary(sessionId);

  return request<TriggerSummaryResponse>(
    `/sessions/${sessionId}/trigger_summary`,
    { method: "POST" }
  );
}

/**
 * 获取会话对应的向量记忆列表。
 * GET /sessions/{session_id}/memories
 */
export async function getSessionMemories(
  sessionId: number,
  params: GetSessionMemoriesParams = {}
): Promise<GetSessionMemoriesResponse> {
  const {
    q = "",
    scope = "all",
    status = "active",
    limit = 20,
    offset = 0,
  } = params;

  if (USE_MOCK) return mock.getSessionMemories(sessionId, params);

  const query = [
    `scope=${scope}`,
    `status=${status}`,
    `limit=${limit}`,
    `offset=${offset}`,
  ];
  if (q.trim()) {
    query.push(`q=${encodeURIComponent(q.trim())}`);
  }
  return request<GetSessionMemoriesResponse>(
    `/sessions/${sessionId}/memories?${query.join("&")}`,
    { method: "GET" }
  );
}

/**
 * 获取角色下各故事线的记忆统计与最近消息，用于角色详情记忆导航。
 * GET /characters/{character_id}/memory-overview
 */
export async function getCharacterMemoryOverview(
  characterId: number,
  limit = 50,
  offset = 0
): Promise<CharacterMemoryOverviewResponse> {
  if (USE_MOCK) return mock.getCharacterMemoryOverview(characterId, limit, offset);

  return request<CharacterMemoryOverviewResponse>(
    `/characters/${characterId}/memory-overview?limit=${limit}&offset=${offset}`,
    { method: "GET" }
  );
}

/**
 * 手动创建向量记忆。
 * POST /sessions/{session_id}/memories
 */
export async function createSessionMemory(
  sessionId: number,
  content: string,
  importanceScore: number = 0.8
): Promise<MemoryCreateResponse> {
  if (USE_MOCK) return mock.createSessionMemory(sessionId, content, importanceScore);

  return request<MemoryCreateResponse>(`/sessions/${sessionId}/memories`, {
    method: "POST",
    body: JSON.stringify({
      content,
      importance_score: importanceScore,
      memory_type: "fact",
    }),
  });
}

/**
 * 更新向量记忆。
 * PUT /sessions/{session_id}/memories/{memory_id}
 */
export async function updateSessionMemory(
  sessionId: number,
  memoryId: number,
  content: string,
  importanceScore: number
): Promise<MemoryUpdateResponse> {
  if (USE_MOCK) return mock.updateSessionMemory(sessionId, memoryId, content, importanceScore);

  return request<MemoryUpdateResponse>(`/sessions/${sessionId}/memories/${memoryId}`, {
    method: "PUT",
    body: JSON.stringify({
      content,
      importance_score: importanceScore,
    }),
  });
}

/**
 * 删除向量记忆。
 * DELETE /sessions/{session_id}/memories/{memory_id}
 */
export async function deleteSessionMemory(
  sessionId: number,
  memoryId: number
): Promise<MemoryDeleteResponse> {
  if (USE_MOCK) return mock.deleteSessionMemory(sessionId, memoryId);

  return request<MemoryDeleteResponse>(`/sessions/${sessionId}/memories/${memoryId}`, {
    method: "DELETE",
  });
}
