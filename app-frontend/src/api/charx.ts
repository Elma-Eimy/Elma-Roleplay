import { request, USE_MOCK, getBaseUrl, getHeaders } from "./config";
import type { CharxPreview, CharxImportRequest, CharxImportResult, CharxStatus } from "@/types/charx";

function requireServer() {
  if (USE_MOCK) throw new Error("离线模式暂不支持 CHARX 导入，请连接后端使用。");
}

export async function previewCharx(filePath: string): Promise<CharxPreview> {
  requireServer();
  return new Promise((resolve, reject) => {
    uni.uploadFile({
      url: `${getBaseUrl()}/characters/charx/preview`, filePath, name: "file", header: getHeaders(),
      success: res => {
        if (res.statusCode < 200 || res.statusCode >= 300) { reject(new Error(`上传失败 ${res.statusCode}: ${res.data}`)); return; }
        try { resolve(JSON.parse(res.data)); }
        catch { reject(new Error("无法读取角色包预览结果")); }
      },
      fail: err => reject(new Error(err.errMsg || "角色包上传失败")),
    });
  });
}

export async function getCharxImages(token: string, offset: number) {
  requireServer();
  return request<{ images: { index: number; thumbnail: string }[]; has_more: boolean }>(`/characters/charx/previews/${token}/images?offset=${offset}`);
}

export async function cancelCharx(token: string) {
  requireServer();
  return request(`/characters/charx/previews/${token}/cancel`, { method: "POST" });
}

export async function getCharxStatus(token: string) {
  requireServer();
  return request<CharxStatus>(`/characters/charx/previews/${token}/status`);
}

export async function importCharx(token: string, body: CharxImportRequest) {
  requireServer();
  return request<CharxImportResult>(`/characters/charx/previews/${token}/import`, { method: "POST", body: JSON.stringify(body) });
}
