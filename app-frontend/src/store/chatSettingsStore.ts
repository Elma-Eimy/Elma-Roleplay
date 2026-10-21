import { ref, computed, watch } from "vue";
import { defineStore } from "pinia";
import { getSettings, DEFAULT_SETTINGS } from "@/api/settings";
import { getBaseUrl } from "@/api/config";
import { EMPTY_GENERATION } from "@/types/generation";
import type { GenerationOverride, ThinkingMode } from "@/types/generation";
import {
  configuredCatalog,
  effectiveGeneration,
  normalizeOverride,
  snapshotGeneration,
  effortLabel,
  modelOptionLabel,
} from "@/utils/generation";

export const useChatSettingsStore = defineStore("chatSettings", () => {
  const defaults = ref({ ...DEFAULT_SETTINGS });
  const catalog = computed(() => configuredCatalog(defaults.value));
  const settingsError = ref("");
  const isLoadingModels = ref(false);
  const activeSessionId = ref<number | null>(null);
  const selection = ref<GenerationOverride>({ ...EMPTY_GENERATION });
  let loadingSelection = false;
  let settingsVersion = 0;
  let server = getBaseUrl();
  let readyEndpoint: string | null = null;
  let pendingModels: { endpoint: string; promise: Promise<void> } | null = null;
  const storageKey = () => `story_generation_v1:${getBaseUrl()}`;
  const readSelections = (): Record<string, unknown> => {
    try {
      const stored = uni.getStorageSync(storageKey());
      return stored && typeof stored === "object"
        ? stored
        : stored
          ? JSON.parse(stored)
          : {};
    } catch {
      return {};
    }
  };
  const persist = () => {
    if (loadingSelection || activeSessionId.value === null || server !== getBaseUrl()) return;
    const values = readSelections();
    values[String(activeSessionId.value)] = { ...selection.value };
    uni.setStorageSync(storageKey(), JSON.stringify(values));
  };
  watch(selection, persist, { deep: true, flush: "sync" });
  function activateSession(id: number) {
    const newServer = getBaseUrl();
    if (activeSessionId.value === id && server === newServer) return;
    if (server !== newServer) {
      defaults.value = { ...DEFAULT_SETTINGS };
      readyEndpoint = null;
    }
    server = newServer;
    loadingSelection = true;
    activeSessionId.value = id;
    selection.value = normalizeOverride(readSelections()[String(id)]);
    loadingSelection = false;
    if (selection.value.model && selection.value.thinking_mode !== "inherit" && selection.value.reasoning_effort !== "inherit")
      freezeSelection();
    else
      void refreshModels();
  }
  function freezeSelection() {
    if (readyEndpoint === getBaseUrl() && server === getBaseUrl() && activeSessionId.value !== null)
      selection.value = snapshotGeneration(defaults.value, selection.value);
  }
  function inheritSession(parent: number, child: number) {
    const values = readSelections();
    values[String(child)] = readyEndpoint === getBaseUrl()
      ? snapshotGeneration(defaults.value, values[String(parent)])
      : normalizeOverride(values[String(parent)]);
    uni.setStorageSync(storageKey(), JSON.stringify(values));
  }
  function resetGeneration() {
    selection.value = snapshotGeneration(defaults.value, EMPTY_GENERATION);
  }
  function removeSession(id: number) {
    const values = readSelections();
    delete values[String(id)];
    uni.setStorageSync(storageKey(), JSON.stringify(values));
    if (activeSessionId.value === id) {
      loadingSelection = true;
      selection.value = { ...EMPTY_GENERATION };
      activeSessionId.value = null;
      loadingSelection = false;
    }
  }
  function refreshModels(): Promise<void> {
    const endpoint = getBaseUrl();
    if (pendingModels?.endpoint === endpoint) return pendingModels.promise;
    const promise = loadModels();
    pendingModels = { endpoint, promise };
    void promise.finally(() => { if (pendingModels?.promise === promise) pendingModels = null; });
    return promise;
  }
  async function loadModels() {
    const version = ++settingsVersion;
    const endpoint = getBaseUrl();
    isLoadingModels.value = true;
    settingsError.value = "";
    try {
      const result = await getSettings();
      if (version === settingsVersion && endpoint === getBaseUrl()) {
        defaults.value = { ...DEFAULT_SETTINGS, ...result };
        readyEndpoint = endpoint;
        freezeSelection();
      }
    } catch {
      if (version === settingsVersion)
        settingsError.value = "模型配置加载失败，请检查连接后重试。";
    } finally {
      if (version === settingsVersion) isLoadingModels.value = false;
    }
  }
  const effective = computed(() =>
    effectiveGeneration(defaults.value, selection.value),
  );
  const modelSummary = computed(
    () =>
      !selection.value.model && isLoadingModels.value ? "正在加载模型…" :
      !selection.value.model && settingsError.value ? "模型配置未加载" :
      `${effective.value.capability ? modelOptionLabel(effective.value.capability, catalog.value) : effective.value.label} · ${effective.value.thinking ? "思考 · " + effortLabel(effective.value.effort || "high") : "思考关闭"}`,
  );
  // 为尚未升级的组件保留派生值，新的请求不再以这个布尔值切换模型。
  const useReasoning = computed({
    get: () => effective.value.thinking,
    set: (value: boolean) => {
      selection.value.thinking_mode = value ? "enabled" : "disabled";
    },
  });
  const modelId = computed({
    get: () => selection.value.model,
    set: (value: string) => {
      selection.value.model = value;
    },
  });
  const thinkingMode = computed({
    get: () => selection.value.thinking_mode,
    set: (value: ThinkingMode) => {
      selection.value.thinking_mode = value;
    },
  });
  const reasoningEffort = computed({
    get: () => selection.value.reasoning_effort,
    set: (value: string) => {
      selection.value.reasoning_effort = value;
    },
  });
  async function requestGeneration(id: number) {
    const endpoint = getBaseUrl();
    if (pendingModels?.endpoint === endpoint) await pendingModels.promise;
    else if (readyEndpoint !== endpoint) await refreshModels();
    if (endpoint !== getBaseUrl() || readyEndpoint !== endpoint)
      throw new Error("模型配置尚未加载，请检查连接后重试。");
    const value =
      activeSessionId.value === id && server === getBaseUrl()
        ? selection.value
        : normalizeOverride(readSelections()[String(id)]);
    if (settingsError.value && (!value.model || value.thinking_mode === "inherit" || value.reasoning_effort === "inherit"))
      throw new Error("模型配置尚未加载，请检查连接后重试。");
    const resolved = snapshotGeneration(defaults.value, value);
    const values = readSelections();
    values[String(id)] = resolved;
    uni.setStorageSync(storageKey(), JSON.stringify(values));
    return {
      model: resolved.model,
      thinking_mode: resolved.thinking_mode,
      reasoning_effort: resolved.reasoning_effort,
    };
  }
  const temperature = ref<number | null>(null);
  const top_p = ref<number | null>(null);
  const presence_penalty = ref<number | null>(null);
  const frequency_penalty = ref<number | null>(null);
  const repetition_penalty = ref<number | null>(null);
  function clearParameters() {
    temperature.value = null;
    top_p.value = null;
    presence_penalty.value = null;
    frequency_penalty.value = null;
    repetition_penalty.value = null;
  }
  function $reset() {
    clearParameters();
    loadingSelection = true;
    activeSessionId.value = null;
    selection.value = { ...EMPTY_GENERATION };
    loadingSelection = false;
  }
  return {
    defaults,
    catalog,
    selection,
    modelId,
    thinkingMode,
    reasoningEffort,
    effective,
    modelSummary,
    useReasoning,
    settingsError,
    isLoadingModels,
    refreshModels,
    activeSessionId,
    activateSession,
    removeSession,
    inheritSession,
    resetGeneration,
    requestGeneration,
    temperature,
    top_p,
    presence_penalty,
    frequency_penalty,
    repetition_penalty,
    clearParameters,
    $reset,
  };
});
