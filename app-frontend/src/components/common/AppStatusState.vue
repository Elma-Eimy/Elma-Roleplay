<template>
  <view
    class="app-status-state"
    :class="[`is-${kind}`, { 'is-compact': compact }]"
    role="status"
    aria-live="polite"
  >
    <view class="status-visual" aria-hidden="true">
      <view v-if="kind === 'loading'" class="loading-dots">
        <view class="loading-dot"></view>
        <view class="loading-dot"></view>
        <view class="loading-dot"></view>
      </view>
      <text v-else class="status-symbol">{{ statusSymbol }}</text>
    </view>

    <view class="status-copy">
      <text class="status-title">{{ resolvedTitle }}</text>
      <text v-if="resolvedDescription" class="status-description">{{ resolvedDescription }}</text>
    </view>

    <view v-if="actionLabel && kind !== 'loading'" class="status-action" role="button" @tap="emit('action')">
      <text class="status-action-label">{{ actionLabel }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import { computed } from "vue";

type StatusKind = "loading" | "empty" | "error" | "offline" | "auth";

const props = withDefaults(defineProps<{
  kind: StatusKind;
  title?: string;
  description?: string;
  actionLabel?: string;
  compact?: boolean;
}>(), {
  title: "",
  description: "",
  actionLabel: "",
  compact: false,
});

const emit = defineEmits<{
  action: [];
}>();

const defaults: Record<StatusKind, { title: string; description: string; symbol: string }> = {
  loading: { title: "正在准备内容", description: "稍等片刻，故事马上继续。", symbol: "" },
  empty: { title: "这里还没有内容", description: "完成第一次创建后，它会出现在这里。", symbol: "◇" },
  error: { title: "内容没有加载成功", description: "请稍后重试，已有数据不会受到影响。", symbol: "!" },
  offline: { title: "当前处于离线状态", description: "恢复网络后即可继续使用在线能力。", symbol: "⌁" },
  auth: { title: "需要完成身份验证", description: "检查访问密钥后再试一次。", symbol: "◌" },
};

const resolvedTitle = computed(() => props.title || defaults[props.kind].title);
const resolvedDescription = computed(() => props.description || defaults[props.kind].description);
const statusSymbol = computed(() => defaults[props.kind].symbol);
</script>

<style scoped>
.app-status-state {
  width: 100%;
  min-height: 300rpx;
  padding: 48rpx 34rpx;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--app-color-border, rgba(38, 51, 46, 0.08));
  border-radius: var(--app-radius-lg, 36rpx);
  background-color: rgba(255, 255, 255, 0.58);
  text-align: center;
}

.app-status-state.is-compact {
  min-height: 0;
  padding: 28rpx;
  flex-direction: row;
  justify-content: flex-start;
  text-align: left;
}

.status-visual {
  width: 72rpx;
  height: 72rpx;
  display: flex;
  flex-shrink: 0;
  align-items: center;
  justify-content: center;
  border-radius: 24rpx;
  color: var(--app-color-primary-strong, #4f8e7c);
  background-color: var(--app-color-primary-soft, rgba(112, 174, 155, 0.14));
}

.is-error .status-visual,
.is-auth .status-visual {
  color: var(--app-color-danger, #d9655d);
  background-color: rgba(217, 101, 93, 0.11);
}

.is-offline .status-visual {
  color: #5d83a1;
  background-color: rgba(139, 184, 220, 0.14);
}

.status-symbol {
  font-size: 36rpx;
  font-weight: 680;
}

.status-copy {
  margin-top: 22rpx;
  display: flex;
  flex-direction: column;
  gap: 7rpx;
}

.is-compact .status-copy {
  min-width: 0;
  margin: 0 0 0 20rpx;
  flex: 1;
}

.status-title {
  color: var(--app-color-text-primary, #26332e);
  font-size: 27rpx;
  font-weight: 680;
}

.status-description {
  color: var(--app-color-text-secondary, #7c8983);
  font-size: 21rpx;
  line-height: 1.5;
}

.status-action {
  min-height: 72rpx;
  margin-top: 24rpx;
  padding: 0 24rpx;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--app-radius-pill, 999rpx);
  background-color: var(--app-color-text-primary, #26332e);
}

.is-compact .status-action {
  min-height: 72rpx;
  margin: 0 0 0 18rpx;
}

.status-action:active {
  transform: scale(0.97);
}

.status-action-label {
  color: #ffffff;
  font-size: 21rpx;
  font-weight: 650;
}

.loading-dots {
  display: flex;
  align-items: center;
  gap: 7rpx;
}

.loading-dot {
  width: 10rpx;
  height: 10rpx;
  border-radius: 50%;
  background-color: var(--app-color-primary, #70ae9b);
  animation: status-pulse 900ms ease-in-out infinite;
}

.loading-dot:nth-child(2) {
  animation-delay: 120ms;
}

.loading-dot:nth-child(3) {
  animation-delay: 240ms;
}

@keyframes status-pulse {
  0%,
  100% {
    opacity: 0.35;
    transform: translateY(2rpx);
  }
  50% {
    opacity: 1;
    transform: translateY(-4rpx);
  }
}
</style>
