<template>
  <view class="generation-picker">
    <view class="generation-field">
      <text class="generation-label">{{ modelLabel }}</text>
      <picker :range="modelOptions.map(item => item.label)" :value="modelIndex" :disabled="!modelOptions.length" @change="selectModel">
        <view class="generation-value"><text>{{ modelOptions[modelIndex]?.label || effectiveId || '正在加载模型…' }}</text><text>⌄</text></view>
      </picker>
    </view>
    <view v-if="capability" class="generation-field">
      <text class="generation-label">思考</text>
      <picker v-if="thinkingOptions.length > 1" :range="thinkingOptions.map(item => item.label)" :value="thinkingIndex" @change="selectThinking">
        <view class="generation-value"><text>{{ thinkingOptions[thinkingIndex]?.label }}</text><text>⌄</text></view>
      </picker>
      <text v-else class="generation-hint">{{ capability.thinking === 'unsupported' ? '此模型不支持思考' : '始终开启' }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed, watch } from "vue";
import type { ModelCapability, ThinkingMode } from "@/types/generation";
import { effortLabel, modelOptionLabel } from "@/utils/generation";
const props = withDefaults(defineProps<{
  catalog: ModelCapability[];
  model: string;
  thinkingMode: ThinkingMode;
  effort: string;
  defaultModel?: string;
  defaultThinking?: boolean;
  defaultEffort?: string | null;
  modelLabel?: string;
}>(), { defaultModel: "", defaultThinking: false, defaultEffort: null, modelLabel: "模型" });
const emit = defineEmits<{
  (event: "update:model", model: string): void;
  (event: "update:thinkingMode", mode: ThinkingMode): void;
  (event: "update:effort", effort: string): void;
}>();
const effectiveId = computed(() => props.model || props.defaultModel);
const capability = computed(() => props.catalog.find(item => item.id === effectiveId.value));
const modelOptions = computed(() => {
  const options = props.catalog.map(item => ({ id: item.id, label: modelOptionLabel(item, props.catalog) }));
  if (effectiveId.value && !options.some(item => item.id === effectiveId.value))
    options.unshift({ id: effectiveId.value, label: effectiveId.value });
  return options;
});
const modelIndex = computed(() => Math.max(0, modelOptions.value.findIndex(item => item.id === effectiveId.value)));
const thinking = computed(() => capability.value?.thinking === 'always' ||
  (capability.value?.thinking === 'toggle' && (props.thinkingMode === 'inherit' ? props.defaultThinking : props.thinkingMode === 'enabled')));
const effectiveEffort = computed(() => {
  const efforts = capability.value?.efforts || [];
  let effort = props.effort === 'inherit' ? props.defaultEffort || 'high' : props.effort;
  if (capability.value?.adapter === 'deepseek')
    effort = ({ minimal: 'low', medium: 'high', xhigh: 'high', ultra: 'max' } as Record<string, string>)[effort] || effort;
  return efforts.includes(effort) ? effort : efforts.includes('high') ? 'high' : efforts[0] || 'high';
});
const thinkingOptions = computed(() => [
  ...(capability.value?.thinking !== 'always' ? [{ value: 'disabled', label: '关闭' }] : []),
  ...(capability.value?.thinking !== 'unsupported' ?
    (capability.value?.efforts.length ? capability.value.efforts.map(value => ({ value, label: effortLabel(value) })) : [{ value: 'enabled', label: '开启' }]) : []),
]);
const thinkingIndex = computed(() => Math.max(0, thinkingOptions.value.findIndex(item => item.value === (thinking.value ? capability.value?.efforts.length ? effectiveEffort.value : 'enabled' : 'disabled'))));
function selectModel(event: { detail: { value: string | number } }) {
  const model = modelOptions.value[Number(event.detail.value)];
  if (model) emit('update:model', model.id);
}
function selectThinking(event: { detail: { value: string | number } }) {
  const option = thinkingOptions.value[Number(event.detail.value)];
  if (!option) return;
  if (option.value !== 'disabled') emit('update:effort', option.value === 'enabled' ? effectiveEffort.value : option.value);
  emit('update:thinkingMode', option.value === 'disabled' ? 'disabled' : 'enabled');
}
watch(() => [effectiveId.value, capability.value?.thinking, props.effort, props.thinkingMode], () => {
  if (!capability.value) return;
  if (capability.value.thinking === 'always' && props.thinkingMode !== 'enabled') emit('update:thinkingMode', 'enabled');
  if (capability.value.thinking === 'unsupported' && props.thinkingMode !== 'disabled') emit('update:thinkingMode', 'disabled');
  if (capability.value.efforts.length && props.effort !== effectiveEffort.value) emit('update:effort', effectiveEffort.value);
}, { immediate: true });
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
.generation-hint {
  font-size: 22rpx;
  color: var(--app-color-text-secondary, #7c8983);
  line-height: 1.7;
  overflow-wrap: anywhere;
}
</style>
