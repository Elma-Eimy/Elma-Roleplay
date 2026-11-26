<template>
  <view class="drawer-sliders-container">
    <view v-for="item in sliders" :key="item.key" class="drawer-slider-row">
      <view class="drawer-slider-header">
        <text class="drawer-slider-label">{{ item.label }}</text>
        <view class="drawer-slider-value-wrapper">
          <text class="drawer-slider-value" :class="{ 'is-default': item.value === null }">
            {{ item.value !== null ? item.value.toFixed(item.digits) : item.defaultLabel }}
          </text>
          <text
            v-if="item.value !== null"
            class="drawer-slider-reset"
            @tap.stop="resetValue(item.key)"
          >重置</text>
        </view>
      </view>
      <slider
        :disabled="item.disabled"
        class="drawer-slider-component"
        :value="Math.round(((item.value ?? item.fallback) + item.offset) * item.scale)"
        :min="item.min"
        :max="item.max"
        :step="item.step"
        activeColor="#70ae9b"
        backgroundColor="rgba(38, 51, 46, 0.1)"
        block-color="#ffffff"
        block-size="18"
        @change="updateValue(item.key, item.scale, item.offset, Number($event.detail.value))"
      />
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { useChatSettingsStore } from "@/store/chatSettingsStore";

type ParamKey = "temperature" | "top_p" | "presence_penalty" | "frequency_penalty" | "repetition_penalty";

const chatSettingsStore = useChatSettingsStore();

const isTopPDisabled = computed(() => {
  const effective = chatSettingsStore.effective;
  return (
    effective.capability?.adapter === "reasoning" ||
    (effective.capability?.adapter === "deepseek" &&
      (/flash/i.test(effective.id) ? !effective.thinking : effective.thinking))
  );
});

const sliders = computed(() => [
  {
    key: "temperature" as ParamKey,
    label: "创意温度 (Temperature)",
    value: chatSettingsStore.temperature,
    fallback: 1.0,
    defaultLabel: "默认 (1.0)",
    digits: 1,
    min: 1,
    max: 20,
    step: 1,
    scale: 10,
    offset: 0,
    disabled: chatSettingsStore.effective.thinking,
  },
  {
    key: "top_p" as ParamKey,
    label: "核采样比例 (Top P)",
    value: chatSettingsStore.top_p,
    fallback: 1.0,
    defaultLabel: "默认 (1.00)",
    digits: 2,
    min: 10,
    max: 100,
    step: 5,
    scale: 100,
    offset: 0,
    disabled: isTopPDisabled.value,
  },
  {
    key: "presence_penalty" as ParamKey,
    label: "存在惩罚 (Presence Penalty)",
    value: chatSettingsStore.presence_penalty,
    fallback: 0.0,
    defaultLabel: "默认 (0.0)",
    digits: 1,
    min: 0,
    max: 40,
    step: 1,
    scale: 10,
    offset: 2,
    disabled: chatSettingsStore.effective.thinking,
  },
  {
    key: "frequency_penalty" as ParamKey,
    label: "频率惩罚 (Frequency Penalty)",
    value: chatSettingsStore.frequency_penalty,
    fallback: 0.0,
    defaultLabel: "默认 (0.0)",
    digits: 1,
    min: 0,
    max: 40,
    step: 1,
    scale: 10,
    offset: 2,
    disabled: chatSettingsStore.effective.thinking,
  },
  {
    key: "repetition_penalty" as ParamKey,
    label: "重复度惩罚 (Repetition Penalty)",
    value: chatSettingsStore.repetition_penalty,
    fallback: 1.0,
    defaultLabel: "默认 (1.00)",
    digits: 2,
    min: 50,
    max: 200,
    step: 5,
    scale: 100,
    offset: 0,
    disabled: chatSettingsStore.effective.capability?.adapter !== "compatible",
  },
]);

const resetValue = (key: ParamKey) => {
  chatSettingsStore[key] = null;
};

const updateValue = (key: ParamKey, scale: number, offset: number, raw: number) => {
  chatSettingsStore[key] = raw / scale - offset;
};
</script>

<style scoped>
@import "./chatDrawer.css";
</style>
