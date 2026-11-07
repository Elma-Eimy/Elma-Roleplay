import { ref, computed, watch, onScopeDispose } from "vue";
import { getMemoryProcessingStatus, triggerSummary } from "@/api/memories";
import { getBaseUrl, USE_MOCK } from "@/api/config";
import { onServerChange } from "@/utils/connectionEvents";
import type { MemoryProcessingStatus } from "@/types/memories";

export function useMemoryProcessing(sessionId: () => number | null, onCompleted: () => void = () => {}) {
  const state = ref<MemoryProcessingStatus | null>(null);
  const loading = ref(false);
  const submitting = ref(false);
  const error = ref("");
  let version = 0;
  let disposed = false;
  let timer: ReturnType<typeof setTimeout> | null = null;
  const busy = computed(() => submitting.value || !state.value || !!error.value || state.value.pending_count > 0);

  function clearTimer() {
    if (timer !== null) clearTimeout(timer);
    timer = null;
  }

  function context() {
    const ticket = ++version, id = sessionId(), server = getBaseUrl();
    return { id, current: () => !disposed && ticket === version && id === sessionId() && server === getBaseUrl() };
  }

  function accept(result: MemoryProcessingStatus) {
    const previous = state.value;
    state.value = result;
    error.value = "";
    if (previous && (result.last_completed_at !== previous.last_completed_at ||
        (previous.pending_count > 0 && result.pending_count === 0))) onCompleted();
  }

  function schedule() {
    clearTimer();
    if (!disposed && sessionId() !== null && !USE_MOCK) timer = setTimeout(() => { void refresh(); }, 5000);
  }

  async function refresh() {
    if (disposed || submitting.value) return;
    clearTimer();
    const request = context();
    if (request.id === null) return;
    loading.value = true;
    try {
      const result = await getMemoryProcessingStatus(request.id);
      if (request.current()) accept(result);
    } catch {
      if (request.current()) error.value = "暂时无法查询记忆进度，请刷新重试。";
    } finally {
      if (request.current()) { loading.value = false; schedule(); }
    }
  }

  async function extract() {
    if (disposed || busy.value || USE_MOCK) return;
    clearTimer();
    const request = context();
    if (request.id === null) return;
    loading.value = false;
    submitting.value = true;
    error.value = "";
    try {
      const result = await triggerSummary(request.id);
      if (request.current()) accept(result);
    } catch {
      if (request.current()) error.value = "提交结果未确认，正在重新查询进度，请勿重复提取。";
    } finally {
      if (request.current()) { submitting.value = false; schedule(); }
    }
  }

  function reset() {
    version++;
    clearTimer();
    state.value = null;
    loading.value = submitting.value = false;
    error.value = "";
    void refresh();
  }
  const release = onServerChange(reset);
  watch(sessionId, reset, { immediate: true, flush: "sync" });
  onScopeDispose(() => { disposed = true; version++; clearTimer(); release(); });
  return { state, loading, submitting, error, busy, refresh, extract };
}
