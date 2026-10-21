<template>
  <view class="generation-picker">
    <view class="generation-field"
      ><text class="generation-label">{{ modelLabel }}</text
      ><picker
        :range="modelOptions.map((item) => item.label)"
        :value="
          Math.max(
            0,
            modelOptions.findIndex((item) => item.id === model),
          )
        "
        @change="
          emit('update:model', modelOptions[Number($event.detail.value)].id)
        "
        ><view class="generation-value"
          ><text>{{
            modelOptions.find((item) => item.id === model)?.label ||
            model ||
            "选择模型"
          }}</text
          ><text>⌄</text></view
        ></picker
      ><text v-if="effectiveId" class="generation-id">{{
        effectiveId
      }}</text></view
    >
    <view class="generation-field"
      ><text class="generation-label">思考模式</text
      ><view class="generation-segments"
        ><button
          v-for="option in modeOptions"
          :key="option.value"
          :class="{ active: thinkingMode === option.value }"
          @tap="emit('update:thinkingMode', option.value)"
        >
          {{ option.label }}
        </button></view
      ></view
    >
    <view v-if="thinking && capability?.efforts.length" class="generation-field"
      ><text class="generation-label">思考强度</text
      ><picker
        :range="effortOptions.map((item) => item.label)"
        :value="
          Math.max(
            0,
            effortOptions.findIndex((item) => item.value === effort),
          )
        "
        @change="
          emit(
            'update:effort',
            effortOptions[Number($event.detail.value)].value,
          )
        "
        ><view class="generation-value"
          ><text>{{
            effortOptions.find((item) => item.value === effort)?.label ||
            effort ||
            "默认强度"
          }}</text
          ><text>⌄</text></view
        ></picker
      ></view
    >
    <text class="generation-hint">{{
      capability?.thinking === "always"
        ? "这个模型始终使用思考模式。"
        : capability?.thinking === "unsupported"
          ? "此模型按普通对话调用。如需思考，请在模型目录配置适配类型。"
          : thinking
            ? "已开启思考。温度与频率、存在惩罚不生效。"
            : "思考已关闭，模型选择保持不变。"
    }}</text>
    <text
      v-if="capability?.adapter === 'deepseek' && /flash/i.test(effectiveId)"
      class="generation-hint"
      >{{
        thinking
          ? "Flash 思考模式的 Top P 有效范围为 0.95–1.00。"
          : "Flash 普通模式固定使用 Top P 1.00。"
      }}</text
    >
  </view>
</template>

<script setup lang="ts">
import { computed, watch } from "vue";
import type { ModelCapability, ThinkingMode } from "@/types/generation";
const props = withDefaults(
  defineProps<{
    catalog: ModelCapability[];
    model: string;
    thinkingMode: ThinkingMode;
    effort: string;
    defaultModel?: string;
    defaultThinking?: boolean;
    defaultEffort?: string | null;
    allowInherit?: boolean;
    modelLabel?: string;
    allowDefaultEffort?: boolean;
  }>(),
  {
    defaultModel: "",
    defaultThinking: false,
    defaultEffort: null,
    allowInherit: true,
    modelLabel: "对话模型",
    allowDefaultEffort: true,
  },
);
const emit = defineEmits<{
  (event: "update:model", model: string): void;
  (event: "update:thinkingMode", mode: ThinkingMode): void;
  (event: "update:effort", effort: string): void;
}>();
const effectiveId = computed(() => props.model || props.defaultModel);
const capability = computed(() =>
  props.catalog.find((item) => item.id === effectiveId.value),
);
const modelOptions = computed(() => [
  ...(props.allowInherit ? [{ id: "", label: "跟随全局默认" }] : []),
  ...props.catalog.map((item) => ({
    id: item.id,
    label: `${item.label} · ${item.id}`,
  })),
]);
const modeOptions = computed(() => [
  ...(props.allowInherit
    ? [{ value: "inherit" as const, label: "跟随默认" }]
    : []),
  ...(capability.value?.thinking !== "unsupported" && capability.value
    ? [{ value: "enabled" as const, label: "开启" }]
    : []),
  ...(capability.value?.thinking !== "always"
    ? [{ value: "disabled" as const, label: "关闭" }]
    : []),
]);
const thinking = computed(
  () =>
    capability.value?.thinking === "always" ||
    (capability.value?.thinking === "toggle" &&
      (props.thinkingMode === "inherit"
        ? props.defaultThinking
        : props.thinkingMode === "enabled")),
);
const effortOptions = computed(() => [
  ...(props.allowInherit
    ? [
        {
          value: "inherit",
          label: `跟随默认${props.defaultEffort ? " · " + effortLabel(props.defaultEffort) : ""}`,
        },
      ]
    : props.allowDefaultEffort
      ? [{ value: "inherit", label: "模型默认强度" }]
      : []),
  ...(capability.value?.efforts || []).map((value) => ({
    value,
    label: effortLabel(value),
  })),
]);
const effortLabel = (value: string) =>
  (
    ({ low: "低", medium: "中", high: "高", max: "最高" }) as Record<
      string,
      string
    >
  )[value] || value;
watch(
  () => [effectiveId.value, capability.value?.thinking],
  () => {
    if (
      capability.value?.thinking === "always" &&
      props.thinkingMode === "disabled"
    )
      emit("update:thinkingMode", props.allowInherit ? "inherit" : "enabled");
    if (
      capability.value?.thinking === "unsupported" &&
      props.thinkingMode === "enabled"
    )
      emit("update:thinkingMode", props.allowInherit ? "inherit" : "disabled");
    if (
      capability.value?.efforts.length &&
      props.effort !== "inherit" &&
      !capability.value.efforts.includes(props.effort)
    )
      emit("update:effort", props.allowInherit || props.allowDefaultEffort ? "inherit" : "high");
  },
  { immediate: true },
);
</script>

<style scoped>
.generation-picker {
  display: flex;
  flex-direction: column;
  gap: 24rpx;
}
.generation-field {
  display: flex;
  flex-direction: column;
  gap: 12rpx;
  min-width: 0;
}
.generation-label {
  font-size: 25rpx;
  font-weight: 600;
  color: var(--app-color-text-primary, #26332e);
}
.generation-value {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 16rpx;
  min-height: 80rpx;
  padding: 10rpx 22rpx;
  box-sizing: border-box;
  border: 1px solid var(--app-color-border, #e1e8e2);
  border-radius: 16rpx;
  background: #f5f8f5;
  font-size: 26rpx;
  color: #3d6550;
}
.generation-value text:first-child {
  min-width: 0;
  overflow-wrap: anywhere;
}
.generation-id,
.generation-hint {
  font-size: 22rpx;
  color: var(--app-color-text-secondary, #7c8983);
  line-height: 1.7;
  overflow-wrap: anywhere;
}
.generation-segments {
  display: flex;
  gap: 12rpx;
}
.generation-segments button {
  flex: 1;
  margin: 0;
  padding: 0 12rpx;
  border-radius: 14rpx;
  line-height: 74rpx;
  font-size: 24rpx;
  color: #7c8983;
  background: #f2f5f2;
}
.generation-segments .active {
  background: #e4f0e8;
  color: #3d7860;
  border: 1px solid #82ad96;
}
</style>
