import { request } from "./config";

// ===================== 类型定义 =====================

export interface AppSettings {
  temperature: number;
  reasoning_mode: boolean;
  context_history_limit: number;
  retrieval_top_k: number;
  retrieval_min_importance: number;
  retrieval_max_distance: number;
  lorebook_scan_depth: number;
  lorebook_token_budget: number;
  lorebook_max_recursive_passes: number;
  cognition_max_words: number;
}

export type SettingsUpdate = Partial<AppSettings>;

export interface UpdateSettingsResponse {
  message: string;
  updated: SettingsUpdate;
}

// ===================== 默认设定值 =====================

export const DEFAULT_SETTINGS: AppSettings = {
  temperature: 0.7,
  reasoning_mode: false,
  context_history_limit: 15,
  retrieval_top_k: 3,
  retrieval_min_importance: 0.3,
  retrieval_max_distance: 1.2,
  lorebook_scan_depth: 5,
  lorebook_token_budget: 3000,
  lorebook_max_recursive_passes: 3,
  cognition_max_words: 200,
};

// ===================== API 接口函数 =====================

/**
 * 获取当前的自定义对话及检索配置。
 * GET /utils/settings
 */
export async function getSettings(): Promise<AppSettings> {
  return request<AppSettings>("/utils/settings");
}

/**
 * 更新自定义对话及检索配置（即时生效且持久化保存）。
 * PUT /utils/settings
 * 注意：所有字段皆为可选。仅上传的字段会被更新。
 */
export async function updateSettings(
  data: SettingsUpdate
): Promise<UpdateSettingsResponse> {
  return request<UpdateSettingsResponse>("/utils/settings", {
    method: "PUT",
    body: JSON.stringify(data),
  });
}
