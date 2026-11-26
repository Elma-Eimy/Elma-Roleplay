import { getBaseUrl } from "@/api/config";

export type ChatDraftKind = "single" | "group";

export function chatDraftEntryKey(kind: ChatDraftKind, sessionId: number): string {
  return `${kind}:${sessionId}`;
}

function storageKey(server = getBaseUrl()): string {
  return `chat_drafts_v1:${encodeURIComponent(server)}`;
}

export function readAllChatDrafts(server = getBaseUrl()): Record<string, string> {
  try {
    const raw = uni.getStorageSync(storageKey(server));
    if (!raw) return {};
    const parsed = typeof raw === "object" ? raw : JSON.parse(String(raw));
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) return {};
    const result: Record<string, string> = {};
    for (const [entryKey, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (typeof value === "string" && value.trim().length > 0) {
        result[entryKey] = value;
      }
    }
    return result;
  } catch {
    return {};
  }
}

export function loadChatDraft(kind: ChatDraftKind, sessionId: number, server = getBaseUrl()): string {
  if (!Number.isSafeInteger(sessionId) || sessionId <= 0) return "";
  return readAllChatDrafts(server)[chatDraftEntryKey(kind, sessionId)] || "";
}

export function saveChatDraft(
  kind: ChatDraftKind,
  sessionId: number,
  text: string,
  server = getBaseUrl()
): void {
  if (!Number.isSafeInteger(sessionId) || sessionId <= 0) return;
  try {
    const key = storageKey(server);
    const map = readAllChatDrafts(server);
    const entryKey = chatDraftEntryKey(kind, sessionId);
    if (!text || !text.trim()) {
      if (!(entryKey in map)) return;
      delete map[entryKey];
      if (Object.keys(map).length === 0) {
        uni.removeStorageSync(key);
      } else {
        uni.setStorageSync(key, JSON.stringify(map));
      }
      return;
    }
    if (map[entryKey] === text) return;
    map[entryKey] = text;
    uni.setStorageSync(key, JSON.stringify(map));
  } catch {
    // 忽略本机存储异常，不阻塞正常输入与发送
  }
}

export function clearChatDraft(kind: ChatDraftKind, sessionId: number, server = getBaseUrl()): void {
  saveChatDraft(kind, sessionId, "", server);
}
