import { ref, watch, onScopeDispose } from "vue";
import { getBaseUrl, USE_MOCK } from "@/api/config";
import { getPortraitSelection } from "@/api/portraits";
import type { PortraitSelection } from "@/types/portraits";

/** 仅接纳当前故事、当前服务器及最新请求的结果。 */
export function usePortraitSelection(sessionId: () => number | null, timeline: () => string) {
  const selection = ref<PortraitSelection | null>(null);
  let version = 0;
  let disposed = false;
  async function refresh() {
    const id = sessionId(), server = getBaseUrl(), ticket = ++version;
    if (!id || USE_MOCK || disposed) { selection.value = null; return; }
    try {
      const result = await getPortraitSelection(id);
      if (!disposed && version === ticket && sessionId() === id && getBaseUrl() === server) selection.value = result;
    } catch {
      if (!disposed && version === ticket) selection.value = null;
    }
  }
  watch([sessionId, () => getBaseUrl()], () => { selection.value = null; void refresh(); }, { immediate: true });
  watch(timeline, () => { void refresh(); });
  function dispose() { disposed = true; version++; selection.value = null; }
  onScopeDispose(dispose);
  return { selection, refresh, dispose };
}
