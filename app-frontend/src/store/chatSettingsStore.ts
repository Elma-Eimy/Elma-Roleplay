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
    server = newServer;
    loadingSelection = true;
    activeSessionId.value = id;
    selection.value = normalizeOverride(readSelections()[String(id)]);
    loadingSelection = false;
  }
  function inheritSession(parent: number, child: number) {
    const values = readSelections();
    if (values[String(parent)]) { values[String(child)] = { ...normalizeOverride(values[String(parent)]) }; uni.setStorageSync(storageKey(), JSON.stringify(values)); }
  }
  function resetGeneration() {
    selection.value = { ...EMPTY_GENERATION };
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
  async function refreshModels() {
    const version = ++settingsVersion;
    const endpoint = getBaseUrl();
    isLoadingModels.value = true;
    settingsError.value = "";
    try {
      const result = await getSettings();
      if (version === settingsVersion && endpoint === getBaseUrl())
        defaults.value = result;
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
      `${effective.value.label} · ${effective.value.thinking ? "思考开启" : "思考关闭"}`,
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
  function requestGeneration(id: number) {
    const value =
      activeSessionId.value === id && server === getBaseUrl()
        ? selection.value
        : normalizeOverride(readSelections()[String(id)]);
    return {
      model: value.model || undefined,
      thinking_mode: value.thinking_mode,
      reasoning_effort:
        value.reasoning_effort === "inherit"
          ? undefined
          : value.reasoning_effort,
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
