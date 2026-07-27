<template>
  <view
    class="app-primary-button"
    :class="{
      'is-block': block,
      'is-disabled': disabled,
      'is-loading': loading,
    }"
    role="button"
    :aria-disabled="disabled || loading"
    @tap="handleTap"
  >
    <view v-if="loading" class="button-spinner" aria-hidden="true"></view>
    <slot v-else name="icon"></slot>
    <text class="button-label">{{ loading ? loadingText : label }}</text>
  </view>
</template>

<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    label: string;
    loadingText?: string;
    disabled?: boolean;
    loading?: boolean;
    block?: boolean;
  }>(),
  {
    loadingText: "请稍候",
    disabled: false,
    loading: false,
    block: false,
  }
);

const emit = defineEmits<{
  tap: [];
}>();

const handleTap = () => {
  if (props.disabled || props.loading) return;
  emit("tap");
};
</script>

<style scoped>
.app-primary-button {
  display: inline-flex;
  min-width: 224rpx;
  height: var(--app-control-height, 88rpx);
  align-items: center;
  justify-content: center;
  gap: 12rpx;
  padding: 0 32rpx;
  border-radius: var(--app-radius-pill, 999rpx);
  background-color: var(--app-color-primary, #70ae9b);
  box-shadow: 0 12rpx 28rpx rgba(79, 142, 124, 0.2);
  color: #ffffff;
  transition:
    transform var(--app-motion-fast, 160ms) ease,
    background-color var(--app-motion-fast, 160ms) ease,
    opacity var(--app-motion-fast, 160ms) ease;
}

.app-primary-button:active {
  background-color: var(--app-color-primary-strong, #4f8e7c);
  transform: scale(0.97);
}

.app-primary-button.is-block {
  width: 100%;
}

.app-primary-button.is-disabled {
  box-shadow: none;
  opacity: 0.48;
}

.button-label {
  color: inherit;
  font-size: var(--app-font-size-body, 28rpx);
  font-weight: 650;
  letter-spacing: 0.4rpx;
}

.button-spinner {
  width: 28rpx;
  height: 28rpx;
  border: 3rpx solid rgba(255, 255, 255, 0.45);
  border-top-color: #ffffff;
  border-radius: 50%;
  animation: button-spin 800ms linear infinite;
}

@keyframes button-spin {
  to {
    transform: rotate(360deg);
  }
}
</style>
