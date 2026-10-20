import { ref, watch, onScopeDispose } from "vue";
import { getBaseUrl } from "@/api/config";
import { getMemoryConsolidations, previewMemoryConsolidation, applyMemoryConsolidation, undoMemoryConsolidation } from "@/api/memories";
import type { MemoryConsolidation } from "@/types/memories";

export function useMemoryConsolidation(sessionId: () => number | null, onChanged: () => void) {
  const batches = ref<MemoryConsolidation[]>([]);
  const current = ref<MemoryConsolidation | null>(null);
  const selected = ref<number[]>([]);
  const busy = ref(false);
  const error = ref("");
  const historyHasMore = ref(false);
  let version = 0;
  let disposed = false;
  let stateServer = getBaseUrl();

  function reset() {
    version++;
    busy.value = false;
    batches.value = [];
    current.value = null;
    selected.value = [];
    error.value = "";
    historyHasMore.value = false;
  }

  const showError = (cause: unknown) => {
    const message = cause instanceof Error ? cause.message : "请求失败，请重试";
    const detail = message.match(/"detail"\s*:\s*"([^"]+)"/);
    return detail?.[1] || (message.startsWith("[API Error") ? "整理请求失败，请稍后重试" : message);
  };

  type Action = (id: number, valid: () => boolean) => Promise<void>;
  async function run(action: Action) {
    const id = sessionId();
    if (id === null || disposed) return;
    if (stateServer !== getBaseUrl()) {
      stateServer = getBaseUrl();
      reset();
      // 服务器中可能存在相同故事/记录 ID，先加载新服务器记录，丢弃旧操作。
      await load();
      return;
    }
    if (busy.value) return;
    const token = ++version;
    const server = getBaseUrl();
    busy.value = true;
    error.value = "";
    const valid = () => !disposed && token === version && sessionId() === id && getBaseUrl() === server;
    try {
      // 各操作在落地 UI 前再次校验会话和服务器。
      await action(id, valid);
    } catch (cause) {
      if (valid()) error.value = showError(cause);
    } finally {
      if (token === version && !disposed) busy.value = false;
    }
  }

  function update(batch: MemoryConsolidation) {
    current.value = batch;
    selected.value = [];
    batches.value = [batch, ...batches.value.filter(item => item.id !== batch.id)].sort((a, b) => b.id - a.id);
  }

  function choose(batch: MemoryConsolidation) {
    if (busy.value) return;
    current.value = batch;
    selected.value = [];
    error.value = "";
  }

  function toggle(id: number) {
    if (busy.value || current.value?.status !== "preview") return;
    selected.value = selected.value.includes(id) ? selected.value.filter(value => value !== id) : [...selected.value, id];
  }

  const load = () => run(async (id, valid) => {
    const response = await getMemoryConsolidations(id);
    if (!valid()) return;
    batches.value = response.items;
    historyHasMore.value = response.has_more;
    current.value = response.items[0] || null;
    selected.value = [];
  });

  const loadMoreHistory = () => run(async (id, valid) => {
    if (!historyHasMore.value) return;
    const response = await getMemoryConsolidations(id, batches.value.length);
    if (!valid()) return;
    const seen = new Set(batches.value.map(batch => batch.id));
    batches.value.push(...response.items.filter(batch => !seen.has(batch.id)));
    historyHasMore.value = response.has_more;
  });

  const preview = (afterId = 0) => run(async (id, valid) => {
    const response = await previewMemoryConsolidation(id, afterId);
    if (valid()) update(response);
  });

  const apply = () => {
    const batch = current.value;
    const groups = [...selected.value];
    if (!batch || batch.status !== "preview" || !groups.length) return Promise.resolve();
    return run(async (id, valid) => {
      const response = await applyMemoryConsolidation(id, batch.id, groups);
      if (!valid()) return;
      update(response);
      onChanged();
    });
  };

  const undo = (batch: MemoryConsolidation) => run(async (id, valid) => {
    const response = await undoMemoryConsolidation(id, batch.id);
    if (!valid()) return;
    update(response);
    onChanged();
  });

  watch(sessionId, () => {
    stateServer = getBaseUrl();
    reset();
    void load();
  }, { immediate: true, flush: "sync" });

  onScopeDispose(() => { disposed = true; version++; });
  return { batches, current, selected, busy, error, historyHasMore, choose, toggle, load, loadMoreHistory, preview, apply, undo };
}
