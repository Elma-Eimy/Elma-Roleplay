import { request, USE_MOCK } from "./config";
import * as mock from "./mock/messages";
import type {
  GetHistoryResponse,
  UpdateMessageResponse,
  DeleteMessageResponse,
  SwitchCandidateResponse,
} from "../types/messages";

/**
 * 获取感知继承关系的、按时间先后排序的会话聊天历史记录。
 * GET /sessions/{session_id}/history?limit={limit}
 */
export async function getSessionHistory(
  sessionId: number,
  limit = 50,
  beforeId?: number
): Promise<GetHistoryResponse> {
  if (USE_MOCK) return mock.getSessionHistory(sessionId, limit, beforeId);

  const url = beforeId !== undefined
    ? `/sessions/${sessionId}/history?limit=${limit}&before_id=${beforeId}`
    : `/sessions/${sessionId}/history?limit=${limit}`;

  return request<GetHistoryResponse>(url);
}

/**
 * 修改单条消息的内容。
 * PUT /sessions/messages/{message_id}
 */
export async function updateMessage(
  messageId: number,
  content: string
): Promise<UpdateMessageResponse> {
  if (USE_MOCK) return mock.updateMessage(messageId, content);

  return request<UpdateMessageResponse>(`/sessions/messages/${messageId}`, {
    method: "PUT",
    body: JSON.stringify({ content }),
  });
}

/**
 * 删除单条消息（回滚/撤销对话状态）。
 * DELETE /sessions/messages/{message_id} -> 改为 POST /sessions/messages/{message_id}/delete 避开移动端及网关限制
 */
export async function deleteMessage(
  messageId: number
): Promise<DeleteMessageResponse> {
  if (USE_MOCK) return mock.deleteMessage(messageId);

  return request<DeleteMessageResponse>(`/sessions/messages/${messageId}/delete`, {
    method: "POST",
  });
}

/**
 * 切换激活的 AI 回复候选版本。
 * POST /chat/switch_candidate
 */
export async function switchCandidate(
  messageId: number
): Promise<SwitchCandidateResponse> {
  if (USE_MOCK) return mock.switchCandidate(messageId);

  return request<SwitchCandidateResponse>("/chat/switch_candidate", {
    method: "POST",
    body: JSON.stringify({ message_id: messageId }),
  });
}
