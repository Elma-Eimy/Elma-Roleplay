import { request, USE_MOCK } from "./config";
import * as mock from "./mock/prompts";
import type { CompiledPromptResponse } from "../types/prompts";

/**
 * 获取当前会话最近编译组装好的提示词。
 * GET /sessions/{session_id}/compile_prompt
 */
export async function getCompiledPrompt(
  sessionId: number
): Promise<CompiledPromptResponse> {
  if (USE_MOCK) return mock.getCompiledPrompt(sessionId);

  return request<CompiledPromptResponse>(`/sessions/${sessionId}/compile_prompt`);
}
