import { ref, watch } from "vue";
import { defineStore } from "pinia";

export const useChatSettingsStore = defineStore("chatSettings", () => {
  /** 是否对聊天回复启用深度思考推理模型 */
  const useReasoning = ref(uni.getStorageSync("elma_use_reasoning") === true);

  // 深度思考模式选择改变时自动写入缓存
  watch(useReasoning, (newVal) => {
    uni.setStorageSync("elma_use_reasoning", newVal);
  });

  /** 自定义采样参数值 (Session overrides, null fallback to backend settings) */
  const temperature = ref<number | null>(null);
  const top_p = ref<number | null>(null);
  const presence_penalty = ref<number | null>(null);
  const frequency_penalty = ref<number | null>(null);
  const repetition_penalty = ref<number | null>(null);

  /** 清空自定义采样参数 */
  function clearParameters() {
    temperature.value = null;
    top_p.value = null;
    presence_penalty.value = null;
    frequency_penalty.value = null;
    repetition_penalty.value = null;
  }

  /** 重置状态 */
  function $reset() {
    clearParameters();
    useReasoning.value = uni.getStorageSync("elma_use_reasoning") === true;
  }

  return {
    // State
    useReasoning,
    temperature,
    top_p,
    presence_penalty,
    frequency_penalty,
    repetition_penalty,
    // Actions
    clearParameters,
    $reset,
  };
});
