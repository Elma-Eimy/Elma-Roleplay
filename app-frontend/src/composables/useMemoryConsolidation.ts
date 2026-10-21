import { ref, watch, onScopeDispose } from "vue";
import { getBaseUrl } from "@/api/config";
import { getMemoryConsolidations, previewMemoryConsolidation, applyMemoryConsolidation, undoMemoryConsolidation, reviewMemoryConsolidationGroup } from "@/api/memories";
import type { MemoryConsolidation, ConsolidationScanMode, ConsolidationScanStatus } from "@/types/memories";

export function useMemoryConsolidation(sessionId: () => number | null, onChanged: () => void) {
  const batches = ref<MemoryConsolidation[]>([]);
  const current = ref<MemoryConsolidation | null>(null);
  const selected = ref<number[]>([]);
  const busy = ref(false);
  const error = ref("");
  const historyHasMore = ref(false);
  const scanStatus = ref<ConsolidationScanStatus | null>(null);
  const editingId = ref<number | null>(null);
  const draftContent = ref("");
  const draftReason = ref("");
  const draftIgnored = ref(false);
  let version = 0;
  let disposed = false;
  let stateServer = getBaseUrl();

  function reset() {
    editingId.value = null;
    version++;
    busy.value = false;
    batches.value = [];
    current.value = null;
    selected.value = [];
    error.value = "";
    historyHasMore.value = false;
    scanStatus.value = null;
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
    scanStatus.value = batch.scan_status || null;
    editingId.value = null;
    current.value = batch;
    selected.value = [];
    batches.value = [batch, ...batches.value.filter(item => item.id !== batch.id)].sort((a, b) => b.id - a.id);
  }

  function protectDraft() {
    const group = current.value?.groups.find(item => item.id === editingId.value);
    const dirty = group && (draftContent.value !== group.content
      || draftReason.value !== (group.ignore_reason || "")
      || draftIgnored.value !== !!group.ignored);
    if (!dirty) return false;
    error.value = "当前组有未保存的修改，请先保存审阅，或点击取消放弃修改";
    return true;
  }

  function choose(batch: MemoryConsolidation) {
    if (busy.value || protectDraft()) return false;
    current.value = batch;
    editingId.value = null;
    selected.value = [];
    error.value = "";
    return true;
  }

  function toggle(id: number) {
    if (busy.value || current.value?.status !== "preview") return;
    const group = current.value.groups.find(item => item.id === id);
    if (!group || group.ignored || group.conflict || editingId.value !== null) return;
    selected.value = selected.value.includes(id) ? selected.value.filter(value => value !== id) : [...selected.value, id];
  }

  function editGroup(id: number) {
    if (busy.value || current.value?.status !== "preview") return;
    if (editingId.value === id || protectDraft()) return;
    const group = current.value.groups.find(item => item.id === id);
    if (!group) return;
    editingId.value = id;
    draftContent.value = group.content;
    draftReason.value = group.ignore_reason || "";
    draftIgnored.value = !!group.ignored;
  }

  const saveReview = () => {
    const batch = current.value;
    const group = batch?.groups.find(item => item.id === editingId.value);
    if (!batch || !group) return Promise.resolve();
    const content = draftContent.value.trim();
    if (content.length < 4 || content.length > 500) {
      error.value = "整理正文须为 4–500 字符";
      return Promise.resolve();
    }
    const input = { expected_revision: batch.review_revision || 0,
      content: content !== group.content ? content : undefined,
      ignored: draftIgnored.value, ignore_reason: draftReason.value.trim() };
    return run(async (id, valid) => {
      const response = await reviewMemoryConsolidationGroup(id, batch.id, group.id, input);
      if (valid()) update(response);
    });
  };

  const load = () => run(async (id, valid) => {
    if (protectDraft()) return;
    const response = await getMemoryConsolidations(id);
    if (!valid()) return;
    batches.value = response.items;
    scanStatus.value = response.scan_status || null;
    historyHasMore.value = response.has_more;
    current.value = response.items[0] || null;
    editingId.value = null;
    selected.value = [];
  });

  const loadMoreHistory = () => run(async (id, valid) => {
    if (!historyHasMore.value) return;
    const response = await getMemoryConsolidations(id, batches.value.length);
    if (!valid()) return;
    const seen = new Set(batches.value.map(batch => batch.id));
    scanStatus.value = response.scan_status || null;
    batches.value.push(...response.items.filter(batch => !seen.has(batch.id)));
    historyHasMore.value = response.has_more;
  });

  const preview = (afterId = 0, mode: ConsolidationScanMode = "full") => run(async (id, valid) => {
    if (protectDraft()) return;
    const response = await previewMemoryConsolidation(id, afterId, mode);
    if (valid()) update(response);
  });

  const continueScan = () => {
    const batch = current.value;
    if (!batch?.has_more) return Promise.resolve();
    const mode = batch.scan_mode || "full";
    return preview(mode === "incremental" ? 0 : batch.next_after_id, mode);
  };

  const apply = () => {
    const batch = current.value;
    const groups = [...selected.value];
    if (!batch || batch.status !== "preview" || !groups.length || editingId.value !== null) return Promise.resolve();
    return run(async (id, valid) => {
      const response = await applyMemoryConsolidation(id, batch.id, groups, batch.review_revision || 0);
      if (!valid()) return;
      update(response);
      onChanged();
    });
  };

  const undo = (batch: MemoryConsolidation) => run(async (id, valid) => {
    if (protectDraft()) return;
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
  return { batches, current, selected, busy, error, historyHasMore, scanStatus, choose, toggle, load, loadMoreHistory, preview, continueScan, apply, undo,
    editingId, draftContent, draftReason, draftIgnored, editGroup, saveReview };
}
