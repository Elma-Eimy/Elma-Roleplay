<template>
  <view class="memory-processing">
    <view class="status-row">
      <text class="status-title">{{ title }}</text>
      <button size="mini" :disabled="loading || submitting" @tap="refresh">刷新</button>
    </view>
    <text v-if="state && state.pending_count > 0" class="status-detail">还有 {{ state.pending_count }} 项任务，完成后自动更新</text>
    <text v-if="reason" class="status-detail">{{ reason }}</text>
    <text v-if="state?.status === 'completed' && state.last_completed_at && !error" class="status-detail">任务完成不一定新增记忆，重复内容会合并，进行中的事件可继续积累。</text>
    <text v-if="completedTime" class="status-detail">最近任务完成：{{ completedTime }}</text>
    <text v-if="error" class="status-error">{{ error }}</text>
    <text v-if="USE_MOCK" class="status-detail">离线模式不执行记忆提取</text>
    <button class="extract-button" :disabled="busy || USE_MOCK" @tap="extract">{{ submitting ? '正在提交…' : '提取当前故事记忆' }}</button>
  </view>
</template>

<script setup lang="ts">
import { computed } from "vue";
import { USE_MOCK } from "@/api/config";
import { useMemoryProcessing } from "@/composables/useMemoryProcessing";
const props = defineProps<{ sessionId: number | null }>();
const emit = defineEmits<{ (e: "completed"): void }>();
const { state, loading, submitting, error, busy, refresh, extract } = useMemoryProcessing(
  () => props.sessionId, () => emit("completed"),
);
const title = computed(() => {
  if (error.value) return "记忆进度暂不可用";
  if (!state.value) return "正在查询记忆进度…";
  if (state.value.status === "retrying") return "部分记忆等待重试";
  if (state.value.processing_count > 0) return "正在处理记忆";
  if (state.value.status === "pending") return "记忆已排队";
  if (state.value.status === "failed") return "部分记忆未能处理";
  return state.value.last_completed_at ? "记忆处理已完成" : "当前没有待处理任务";
});
const reason = computed(() => {
  const codes = state.value?.error_codes || [];
  if (codes.includes("sources_changed")) return "对话来源已变化，旧候选已取消。可重新提取有效对话。";
  if (codes.includes("invalid_extraction_output")) return "模型返回内容未通过校验，系统会自动重试。";
  if (codes.includes("extraction_failed")) return "模型提取暂未成功，系统会自动重试。";
  if (codes.includes("MemoryDecisionDeferred")) return "记忆关系判断暂未完成，系统会自动重试。";
  if (codes.some(code => ["ConnectionError", "TimeoutError", "APITimeoutError", "APIConnectionError"].includes(code))) return "处理所需的服务连接失败或超时，系统会自动重试。";
  if (state.value?.status === "retrying") return "暂未完成处理，系统会自动重试，无需重复提取。";
  if (state.value?.status === "failed") return "任务已取消，请确认当前故事后重新提取。";
  return "";
});
const completedTime = computed(() => {
  const value = state.value?.last_completed_at;
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
});
</script>

<style scoped>
.memory-processing { display: flex; flex-direction: column; gap: 12rpx; padding: 20rpx; border-radius: var(--app-radius-sm); background: var(--app-color-background); }
.status-row { display: flex; align-items: center; justify-content: space-between; gap: 12rpx; }
.status-title { font-size: 25rpx; font-weight: 600; color: var(--app-color-text-primary); }
.status-row button { flex-shrink: 0; margin: 0; }
.status-detail, .status-error { font-size: 23rpx; line-height: 1.6; color: var(--app-color-text-secondary); overflow-wrap: anywhere; }
.status-error { color: var(--app-color-danger); }
.extract-button { margin: 4rpx 0 0; font-size: 25rpx; }
</style>
