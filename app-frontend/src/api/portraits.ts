import { request, USE_MOCK, getBaseUrl, getHeaders } from "./config";
import type { CharacterPortrait, PortraitSelection } from "@/types/portraits";

function requireServer() {
  if (USE_MOCK) throw new Error("离线模式暂不支持多立绘，请连接后端使用。");
}

export async function getPortraits(characterId: number, offset = 0) {
  requireServer();
  return request<{ portraits: CharacterPortrait[]; total: number; has_more: boolean }>(`/characters/${characterId}/portraits${offset ? `?offset=${offset}` : ''}`);
}

export async function uploadPortrait(characterId: number, filePath: string): Promise<CharacterPortrait> {
  requireServer();
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: `${getBaseUrl()}/characters/${characterId}/portraits`,
      filePath, name: "file", header: getHeaders(),
      success: res => {
        if (res.statusCode < 200 || res.statusCode >= 300) {
          reject(new Error(`上传失败 ${res.statusCode}: ${res.data}`));
          return;
        }
        try { resolve(JSON.parse(res.data)); }
        catch { reject(new Error("无法读取立绘上传结果")); }
      },
      fail: err => reject(new Error(err.errMsg || "立绘上传失败")),
    });
  });
}

export async function renamePortrait(characterId: number, portraitId: number, name: string) {
  requireServer();
  return request<CharacterPortrait>(`/characters/${characterId}/portraits/${portraitId}`, { method: "PUT", body: JSON.stringify({ name }) });
}

export async function deletePortrait(characterId: number, portraitId: number) {
  requireServer();
  return request<{ message: string }>(`/characters/${characterId}/portraits/${portraitId}/delete`, { method: "POST" });
}

export async function getPortraitSelection(sessionId: number) {
  requireServer();
  return request<PortraitSelection>(`/sessions/${sessionId}/portrait`);
}

export async function setPortraitSelection(sessionId: number, portraitId: number | null, revision: string) {
  requireServer();
  return request<PortraitSelection>(`/sessions/${sessionId}/portrait`, {
    method: "PUT", body: JSON.stringify({ portrait_id: portraitId, expected_revision: revision }),
  });
}
